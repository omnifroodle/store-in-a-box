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

/// The only writer to `store.*`. Every write is one `inBatch` (the transaction and the allocation it opens or
/// closes); the ledger state is recomputed after every local write and on every change to `store.transaction` or
/// `store.exception`, and `local.unit_state` is rewritten from it. Call from the main thread.
public final class CustodyStore {
    public static let storeScope = "store"
    public static let localScope = "local"
    public static let replicatedCollections = ["product", "trip", "allocation", "transaction", "exception"]
    public static let localCollections = ["unit_state", "device"]

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
    private let subject: CurrentValueSubject<LedgerState, Never>
    private var tokens: [ListenerToken] = []
    private(set) var lastHLC: HLC?
    /// Test seam: runs inside the write batch right after the transaction is saved.
    var afterTransactionWrite: (() throws -> Void)?

    /// Recomputed on any `store.transaction` or `store.exception` change.
    public var state: AnyPublisher<LedgerState, Never> { subject.eraseToAnyPublisher() }
    public var currentState: LedgerState { subject.value }

    public init(database: Database, identity: DeviceIdentity, clock: Clock) throws {
        try Self.prepare(database)
        self.database = database
        self.identity = identity
        self.clock = clock
        transactions = try database.collection(name: "transaction", scope: Self.storeScope)!
        allocations = try database.collection(name: "allocation", scope: Self.storeScope)!
        exceptions = try database.collection(name: "exception", scope: Self.storeScope)!
        unitStates = try database.collection(name: "unit_state", scope: Self.localScope)!
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
        let known = try known(unit)
        let txn = movement(.sale, unit: unit, from: known?.holder ?? identity.box, to: Custodian.customer,
                           prev: known?.latest?.id, fromAllocation: known?.allocation, toAllocation: nil,
                           basket: basket ?? UUID().uuidString.lowercased(), price: price, tender: tender)
        try commit(txn)
        return txn
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

    // MARK: - Derived state

    /// Re-reads every transaction and exception, merges their clocks, reduces, rewrites `local.unit_state` and
    /// publishes the state. Also the Diagnostics screen's "Rebuild derived state".
    @discardableResult
    public func rebuild() throws -> LedgerState {
        let txns: [Transaction] = try all(transactions)
        let excs: [ExceptionDoc] = try all(exceptions)
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
        }
        subject.send(state)
        return state
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

    /// What this device knows of a unit, from `local.unit_state`; nil when it has no record.
    func known(_ unit: String) throws -> Known? {
        guard let record: UnitRecord = try load(id: unit, from: unitStates) else { return nil }
        let latest: Transaction? = try record.latestTxn.flatMap { try load(id: $0, from: transactions) }
        if record.state == .disputed { return Known(holder: latest?.toCustodian, allocation: latest?.toAllocation, latest: latest) }
        return Known(holder: record.holder, allocation: record.allocation, latest: latest)
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
        try database.inBatch {
            try save(txn, id: txn.id, in: transactions)
            try afterTransactionWrite?()
            for alloc in changed { try save(alloc, id: alloc.id, in: allocations) }
        }
        try rebuild()
    }

    func all<T: Decodable>(_ collection: Collection) throws -> [T] {
        let query = try database.createQuery(
            "SELECT META().id AS id FROM `\(collection.scope.name)`.`\(collection.name)`")
        return try query.execute().allResults().compactMap { row in
            row.string(forKey: "id").flatMap { try? load(id: $0, from: collection) }  // undecodable: skipped
        }
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
