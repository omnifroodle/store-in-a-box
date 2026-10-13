import Combine
import CouchbaseLiteSwift
import Foundation

/// Who this device is, from the pairing payload.
public struct DeviceIdentity: Codable, Equatable {
    public var device: String
    public var box: String
    public var trip: String
    public var store: String
    public init(device: String, box: String, trip: String, store: String = Custodian.store) {
        self.device = device; self.box = box; self.trip = trip; self.store = store
    }
}

/// `local.unit_state`: the reducer's view of one unit, plus the latest movement this device knows for it (the
/// leaf, or for a disputed unit the canonical movement with the greatest hlc), which the write path uses as
/// `prev_txn`.
struct UnitRecord: Codable, Equatable {
    var sku: String
    var holder: String?
    var allocation: String?
    var state: CustodyState
    var lastTxn: String?
    var latestTxn: String?
    enum CodingKeys: String, CodingKey { case sku, holder, allocation, state, lastTxn = "last_txn", latestTxn = "latest_txn" }
}

/// One line of a basket sale: the unit and the price it sells at.
public struct SaleLine: Equatable {
    public var unit: String
    public var price: Money
    public init(unit: String, price: Money) { self.unit = unit; self.price = price }
}

/// The only writer to `store.*`. Every write is one `inBatch` (the transaction and the allocation it opens or
/// closes); the ledger state is recomputed after every local write and on every change to `store.transaction` or
/// `store.exception`, and `local.unit_state` is rewritten from it. Call from the main thread.
public final class CustodyStore {
    public enum Failure: Error, Equatable {
        /// A basket names the same unit on two lines.
        case sameUnitTwice
    }

    public static let storeScope = "store"
    public static let localScope = "local"
    public static let replicatedCollections = ["product", "trip", "allocation", "transaction", "exception"]
    public static let localCollections = ["unit_state", "device", "drop_log"]

    /// Creates (or opens) the five replicated `store` collections and the never-replicated `local` ones.
    public static func prepare(_ db: Database) throws {
        for name in replicatedCollections { _ = try db.createCollection(name: name, scope: storeScope) }
        for name in localCollections { _ = try db.createCollection(name: name, scope: localScope) }
    }

    public let database: Database
    public let identity: DeviceIdentity
    let clock: Clock
    let transactions: Collection
    let allocations: Collection
    let exceptions: Collection
    let unitStates: Collection
    let dropLog: DropLog
    private let subject: CurrentValueSubject<LedgerState, Never>
    private let dropSubject = CurrentValueSubject<[DropRecord], Never>([])
    private var tokens: [ListenerToken] = []
    private(set) var lastHLC: HLC?
    /// Test seam: runs inside the write batch right after each transaction is saved.
    var afterTransactionWrite: (() throws -> Void)?
    /// Whether the box replicator reported this document id pulled, for a drop's `source` (`box`). Set by whoever
    /// owns the replicator; nil means it is never known, and a drop not written here is `peer`.
    public var pulledFromBox: ((String) -> Bool)?

    /// Recomputed on any `store.transaction` or `store.exception` change.
    public var state: AnyPublisher<LedgerState, Never> { subject.eraseToAnyPublisher() }
    public var currentState: LedgerState { subject.value }
    /// The documents the last rebuild dropped (rule 0), as `local.drop_log` entries, newest first; published after
    /// every rebuild, `[]` when nothing was dropped.
    public var drops: AnyPublisher<[DropRecord], Never> { dropSubject.eraseToAnyPublisher() }
    public var currentDrops: [DropRecord] { dropSubject.value }

    public init(database: Database, identity: DeviceIdentity, clock: Clock) throws {
        try Self.prepare(database)
        self.database = database
        self.identity = identity
        self.clock = clock
        transactions = try database.collection(name: "transaction", scope: Self.storeScope)!
        allocations = try database.collection(name: "allocation", scope: Self.storeScope)!
        exceptions = try database.collection(name: "exception", scope: Self.storeScope)!
        unitStates = try database.collection(name: "unit_state", scope: Self.localScope)!
        dropLog = DropLog(database: database, collection: try database.collection(name: "drop_log", scope: Self.localScope)!)
        subject = CurrentValueSubject(.empty(store: identity.store))
        try rebuild()
        for collection in [transactions, exceptions] {
            tokens.append(collection.addChangeListener(queue: .main) { [weak self] _ in _ = try? self?.rebuild() })
        }
    }

    deinit {
        tokens.forEach { $0.remove() }
        // Couchbase Lite's change notification holds its Collection unowned: keep ours alive until notifications
        // already queued on main have run.
        let collections = [transactions, exceptions]
        DispatchQueue.main.async { _ = collections }
    }

    // MARK: - Writes

    /// `to` is this device, or its box in pack mode (`actingFor` the box, scanning units out of the store). Never
    /// waits for replication and never refuses: with no record of the unit, `prev_txn` and `from_allocation` are
    /// null (the first scan out of the store, or a blind take, which the ledger links under the pack, rule 1).
    @discardableResult
    public func checkOut(unit: String, from: String, to: String, actingFor box: String? = nil) throws -> Transaction {
        let sku = Ledger.skuOf(unit)
        let known = try known(unit)
        let fromAllocation = known?.holder == from ? known?.allocation : nil
        let parent = try fromAllocation ?? (box == nil ? activeAllocation(custodian: from, sku: sku)?.id : nil)
        var opened: Allocation?
        var toAllocation = try activeAllocation(custodian: to, sku: sku, parent: parent, matchParent: true)?.id
        if toAllocation == nil {
            let alloc = Allocation(trip: identity.trip, box: identity.box, sku: sku, custodian: to, parent: parent,
                                   fromCustodian: from, openedBy: identity.device, openedAt: tick().string)
            opened = alloc
            toAllocation = alloc.id
        }
        let txn = movement(.checkOut, unit: unit, from: from, to: to, prev: known?.latest?.id,
                           fromAllocation: fromAllocation, toAllocation: toAllocation)
        try commit(txn, allocations: opened.map { [$0] } ?? [])
        return txn
    }

    /// Back to the parent of the holder's allocation (the box's, in Phase 0). Never fails because the record
    /// disagrees: a unit with no record comes `from: "unknown"`; rule 6 flags both cases and the movement stands.
    /// Closes this device's allocation when its derived count reaches zero.
    @discardableResult
    public func checkIn(unit: String) throws -> Transaction {
        let sku = Ledger.skuOf(unit)
        guard let known = try known(unit), let latest = known.latest else {
            let txn = movement(.checkIn, unit: unit, from: Custodian.unknown, to: identity.box, prev: nil,
                               fromAllocation: nil, toAllocation: nil)
            try commit(txn)
            return txn
        }
        let holderAllocation: Allocation? = try known.allocation.flatMap { try load(id: $0, from: allocations) }
        let parent: Allocation? = try holderAllocation?.parent.flatMap { try load(id: $0, from: allocations) }
        let toAllocation = try holderAllocation?.parent ?? activeAllocation(custodian: identity.box, sku: sku)?.id
        let txn = movement(.checkIn, unit: unit, from: known.holder ?? latest.toCustodian,
                           to: parent?.custodian ?? identity.box, prev: latest.id,
                           fromAllocation: known.allocation, toAllocation: toAllocation)
        var closed: [Allocation] = []
        if var mine = holderAllocation, mine.custodian == identity.device, mine.openedBy == identity.device,
           mine.status == .active {
            let after = Ledger.reduce(transactions: Array(currentState.transactions.values) + [txn],
                                      resolutions: currentState.resolutions, store: identity.store)
            if after.allocationCounts[mine.id, default: 0] == 0 {
                mine.status = .closed
                mine.closedAt = txn.hlc
                closed.append(mine)
            }
        }
        try commit(txn, allocations: closed)
        return txn
    }

    /// A sale from the unit's holder as this device knows it (this device, or the box when selling off the table);
    /// with no record, a blind sale from the box. `basket` defaults to a new basket of one.
    @discardableResult
    public func sell(unit: String, tender: Tender, price: Money, basket: String? = nil) throws -> Transaction {
        try sell(basket: [SaleLine(unit: unit, price: price)], tender: tender, id: basket)[0]
    }

    /// A whole basket: one `sale` per line, each as `sell(unit:)` would write it, all sharing the basket id `id` (a
    /// new one when nil) and the tender. One `inBatch` for every line, so the basket commits whole or not at all, and
    /// the state is published once, after the commit: a subscriber never sees part of a basket. The units must be
    /// distinct.
    @discardableResult
    public func sell(basket lines: [SaleLine], tender: Tender, id: String? = nil) throws -> [Transaction] {
        guard !lines.isEmpty else { return [] }
        guard Set(lines.map(\.unit)).count == lines.count else { throw Failure.sameUnitTwice }
        let basket = id ?? UUID().uuidString.lowercased()
        let txns = try lines.map { line -> Transaction in
            let known = try known(line.unit)
            return movement(.sale, unit: line.unit, from: known?.holder ?? identity.box, to: Custodian.customer,
                            prev: known?.latest?.id, fromAllocation: known?.allocation, toAllocation: nil,
                            basket: basket, price: line.price, tender: tender)
        }
        try commit(txns)
        return txns
    }

    /// Writes the exception documents this device's detector owes for the current state, only those whose id does
    /// not already exist locally (rule 7: detectors only create). Returns what it wrote. Reads `currentState` and
    /// publishes nothing, so a subscriber to `state` may call it.
    @discardableResult
    public func detectAndWriteExceptions() throws -> [ExceptionDoc] {
        let state = currentState
        let fresh = try Ledger.exceptions(for: state, detector: identity.device, trip: identity.trip, box: identity.box)
            .filter { try exceptions.document(id: $0.id) == nil }
        guard !fresh.isEmpty else { return [] }
        let at = tick().string
        let docs = fresh.map { doc -> ExceptionDoc in
            var stamped = doc
            stamped.detectedAt = at
            return stamped
        }
        try database.inBatch { for doc in docs { try save(doc, id: doc.id, in: exceptions) } }
        return docs
    }

    #if DEBUG
    /// Diagnostics' drop check (Debug builds only): a take from the box as an app on a newer schema would write it
    /// (`v: 2`). Rule 0 drops it here (`source: local`) and on every device it reaches (`peer` or `box`), as
    /// `newer schema: update the app`. Returns its id.
    @discardableResult
    public func writeNewerSchemaMovement(unit: String) throws -> String {
        let txn = movement(.checkOut, unit: unit, from: identity.box, to: identity.device, prev: nil,
                           fromAllocation: nil, toAllocation: nil)
        guard case .object(var body) = try JSONValue(encoding: txn) else { return txn.id }
        body["_id"] = nil
        body["v"] = .int(2)
        try transactions.save(document: MutableDocument(id: txn.id, json: JSONValue.object(body).canonical))
        try rebuild()
        return txn.id
    }
    #endif

    // MARK: - Derived state

    /// Re-reads every transaction and exception, drops what fails its schema (rule 0) into `local.drop_log`, merges
    /// the accepted ones' clocks, reduces them, rewrites `local.unit_state` and publishes the state and the drops.
    /// Also the Diagnostics screen's "Rebuild derived state".
    @discardableResult
    public func rebuild() throws -> LedgerState {
        let (txns, txnDrops): ([Transaction], [Drop]) = try all(transactions)
        let (excs, excDrops): ([ExceptionDoc], [Drop]) = try all(exceptions)
        // Best effort: the log never fails the rebuild (DropLog.record does not throw).
        let drops = dropLog.record(excDrops + txnDrops, now: Self.rfc3339(clock.nowMs())) { self.source(of: $0) }
        observe(txns.map(\.hlc) + excs.compactMap { $0.detectedBy == identity.device ? $0.detectedAt : nil })
        let state = Ledger.reduce(transactions: txns, resolutions: excs, store: identity.store)
        var latest: [String: Transaction] = [:]
        for t in state.transactions.values where !state.setAside.contains(t.id) {
            if let kept = latest[t.unitID], Ledger.order(kept) > Ledger.order(t) { continue }
            latest[t.unitID] = t
        }
        try database.inBatch {
            for (unitID, unit) in state.units {
                let record = UnitRecord(sku: unit.sku, holder: unit.holder, allocation: unit.allocation,
                                        state: unit.state, lastTxn: unit.lastTxn,
                                        latestTxn: unit.lastTxn ?? latest[unitID]?.id)
                if try load(id: unitID, from: unitStates) != record { try save(record, id: unitID, in: unitStates) }
            }
            // A unit no longer in the state (its movements were dropped) has no record: the write path then treats
            // it as the screens do, as a unit this device does not know (a blind movement, which rule 1 links).
            let query = try database.createQuery("SELECT META().id AS id FROM `\(Self.localScope)`.`unit_state`")
            for row in try query.execute().allResults() {
                guard let id = row.string(forKey: "id"), state.units[id] == nil,
                      let stale = try unitStates.document(id: id) else { continue }
                try unitStates.delete(document: stale)
            }
        }
        subject.send(state)
        dropSubject.send(drops)
        return state
    }

    /// Where a dropped document came from: `local` when its id names this device (a transaction's HLC, an
    /// exception's detector), `box` when the box replicator reported it pulled, else `peer` (inferred).
    func source(of drop: Drop) -> String {
        let parts = drop.id.components(separatedBy: "::")
        let writer: String? = switch parts.first {
        case "txn" where parts.count == 2: HLC(parts[1])?.device
        case "exc" where parts.count >= 2: parts[1]
        default: nil
        }
        if writer == identity.device { return "local" }
        return pulledFromBox?(drop.id) == true ? "box" : "peer"
    }

    static func rfc3339(_ ms: Int64) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: Date(timeIntervalSince1970: Double(ms) / 1000))
    }

    /// `hlc_receive` on what was pulled: the local clock stays ahead of every transaction it has seen.
    private func observe(_ values: [String]) {
        var newestRemote: HLC?
        for value in values {
            guard let h = HLC(value) else { continue }
            if h.device == identity.device {
                if lastHLC.map({ h > $0 }) ?? true { lastHLC = h }
            } else if newestRemote.map({ h > $0 }) ?? true {
                newestRemote = h
            }
        }
        if let remote = newestRemote, lastHLC.map({ remote > $0 }) ?? true {
            lastHLC = HLC.receive(local: lastHLC, remote: remote, clock: clock, device: identity.device)
        }
    }

    // MARK: - Helpers

    struct Known { var holder: String?; var allocation: String?; var latest: Transaction? }

    /// What this device knows of a unit, from `local.unit_state`; nil when it has no record, or when the movement the
    /// record names no longer passes rule 0 (replaced by an invalid revision since the last rebuild): a dropped
    /// document never refuses a scan, it makes the unit one this device does not know.
    func known(_ unit: String) throws -> Known? {
        guard let record: UnitRecord = try load(id: unit, from: unitStates) else { return nil }
        var latest: Transaction?
        if let id = record.latestTxn {
            guard let valid = try validTransaction(id) else { return nil }
            latest = valid
        }
        if record.state == .disputed { return Known(holder: latest?.toCustodian, allocation: latest?.toAllocation, latest: latest) }
        return Known(holder: record.holder, allocation: record.allocation, latest: latest)
    }

    /// `store.transaction`'s document `id` through rule 0: nil when it is missing or would be dropped.
    func validTransaction(_ id: String) throws -> Transaction? {
        guard let doc = try transactions.document(id: id),
              let body = try? JSONDecoder().decode([String: JSONValue].self, from: Data(doc.toJSON().utf8)) else { return nil }
        return DocumentCheck.ingest([(id, body)], collection: "transaction", as: Transaction.self).accepted.first
    }

    func activeAllocation(custodian: String, sku: String, parent: String? = nil,
                          matchParent: Bool = false) throws -> Allocation? {
        let query = try database.createQuery(
            "SELECT META().id AS id FROM `store`.`allocation` WHERE custodian = $c AND sku = $s AND trip = $t AND status = 'active'")
        query.parameters = Parameters().setString(custodian, forName: "c").setString(sku, forName: "s")
            .setString(identity.trip, forName: "t")
        let found: [Allocation] = try query.execute().allResults().compactMap { row in
            try row.string(forKey: "id").flatMap { try load(id: $0, from: allocations) }
        }
        return found.filter { !matchParent || $0.parent == parent }.min { $0.id < $1.id }
    }

    private func tick() -> HLC {
        let next = HLC.now(clock: clock, last: lastHLC, device: identity.device)
        lastHLC = next
        return next
    }

    private func movement(_ kind: MovementKind, unit: String, from: String, to: String, prev: String?,
                          fromAllocation: String?, toAllocation: String?, basket: String? = nil, price: Money? = nil,
                          tender: Tender? = nil) -> Transaction {
        let hlc = tick().string
        let clockString = ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: Double(clock.nowMs()) / 1000))
        return Transaction(id: "txn::" + hlc, trip: identity.trip, box: identity.box, kind: kind, unitID: unit,
                           sku: Ledger.skuOf(unit), fromCustodian: from, toCustodian: to, prevTxn: prev,
                           fromAllocation: fromAllocation, toAllocation: toAllocation, device: identity.device,
                           hlc: hlc, deviceClock: clockString, boxClock: nil, basket: basket, price: price,
                           tender: tender)
    }

    /// One batch: the transaction and the allocations it opens or closes, nothing else.
    private func commit(_ txn: Transaction, allocations changed: [Allocation] = []) throws {
        try commit([txn], allocations: changed)
    }

    /// One batch for the transactions (a basket's sales) and the allocations they open or close, then one rebuild:
    /// nothing is published until the batch has committed, and nothing at all when it throws.
    private func commit(_ txns: [Transaction], allocations changed: [Allocation] = []) throws {
        try database.inBatch {
            for txn in txns {
                try save(txn, id: txn.id, in: transactions)
                try afterTransactionWrite?()
            }
            for alloc in changed { try save(alloc, id: alloc.id, in: allocations) }
        }
        try rebuild()
    }

    /// Every document of `collection`, through rule 0: the ones that pass their schema, decoded, and a drop for each
    /// one that does not (never skipped: `DocumentCheck` reads any JSON object).
    func all<T: Decodable>(_ collection: Collection) throws -> ([T], [Drop]) {
        let query = try database.createQuery(
            "SELECT META().id AS id FROM `\(collection.scope.name)`.`\(collection.name)`")
        var bodies: [(id: String, body: [String: JSONValue])] = []
        var unreadable: [Drop] = []
        for row in try query.execute().allResults() {
            guard let id = row.string(forKey: "id"), let doc = try collection.document(id: id) else { continue }
            do {
                bodies.append((id, try JSONDecoder().decode([String: JSONValue].self, from: Data(doc.toJSON().utf8))))
            } catch {
                unreadable.append(Drop(id: id, collection: collection.name, code: .malformed,
                                       detail: "the document is not JSON the app can read: \(error)"))
            }
        }
        let result = DocumentCheck.ingest(bodies, collection: collection.name, as: T.self)
        return (result.accepted, result.drops + unreadable)
    }

    func load<T: Decodable>(id: String, from collection: Collection) throws -> T? {
        guard let doc = try collection.document(id: id) else { return nil }
        var body = try JSONDecoder().decode([String: JSONValue].self, from: Data(doc.toJSON().utf8))
        body["_id"] = .string(doc.id)
        return try JSONDecoder().decode(T.self, from: JSONEncoder().encode(body))
    }

    func save<T: Encodable>(_ value: T, id: String, in collection: Collection) throws {
        let encoder = JSONEncoder()
        encoder.userInfo[.omitDocumentID] = true
        let json = String(decoding: try encoder.encode(value), as: UTF8.self)
        if let existing = try collection.document(id: id) {
            try collection.save(document: existing.toMutable().setJSON(json))
        } else {
            try collection.save(document: MutableDocument(id: id, json: json))
        }
    }
}
