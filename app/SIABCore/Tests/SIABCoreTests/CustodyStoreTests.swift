import CouchbaseLiteSwift
import XCTest
@testable import SIABCore

/// CustodyStore against a real (temporary) Couchbase Lite database; the neighbours are faked by saving documents
/// "as if pulled" straight into `store.*`.
final class CustodyStoreTests: XCTestCase {
    static let trip = "trip-2026-10-18-riverfest"
    static let unit = "JKT-RAIN-M-BLU#001"
    var directory: URL!
    var database: Database!
    var clock: FakeClock!
    var store: CustodyStore!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        var config = DatabaseConfiguration()
        config.directory = directory.path
        database = try Database(name: "test", config: config)
        clock = FakeClock()
        store = try CustodyStore(database: database, identity: DeviceIdentity(device: "tablet-a", box: "box-07",
                                                                              trip: Self.trip), clock: clock)
    }

    override func tearDownWithError() throws {
        store = nil
        // Let change notifications already queued on main run while the database is still open.
        let drained = expectation(description: "main queue drained")
        DispatchQueue.main.async { drained.fulfill() }
        wait(for: [drained], timeout: 10)
        try database.close()
        try Database.delete(withName: "test", inDirectory: directory.path)
        try? FileManager.default.removeItem(at: directory)
    }

    // MARK: - Fakes

    /// A transaction another device wrote, saved as if replication had pulled it.
    @discardableResult
    func pulled(_ kind: MovementKind, from: String, to: String, prev: String?, device: String, ms: Int64,
                fromAllocation: String? = nil, toAllocation: String? = nil) throws -> Transaction {
        let hlc = HLC(ms: ms, counter: 0, device: device).string
        let txn = Transaction(id: "txn::" + hlc, trip: Self.trip, box: "box-07", kind: kind, unitID: Self.unit,
                              sku: Ledger.skuOf(Self.unit), fromCustodian: from, toCustodian: to, prevTxn: prev,
                              fromAllocation: fromAllocation, toAllocation: toAllocation, device: device, hlc: hlc,
                              deviceClock: "2026-10-18T13:00:00Z")
        try store.save(txn, id: txn.id, in: store.transactions)
        return txn
    }

    /// The pack (store to box) as tablet-b wrote it, with the box's allocation.
    @discardableResult
    func pulledPack(ms: Int64 = 1_792_328_300_000) throws -> Transaction {
        let alloc = Allocation(trip: Self.trip, box: "box-07", sku: Ledger.skuOf(Self.unit), custodian: "box-07",
                               parent: nil, fromCustodian: Custodian.store, openedBy: "tablet-b",
                               openedAt: HLC(ms: ms - 1, counter: 0, device: "tablet-b").string)
        try store.save(alloc, id: alloc.id, in: store.allocations)
        return try pulled(.checkOut, from: Custodian.store, to: "box-07", prev: nil, device: "tablet-b", ms: ms,
                          toAllocation: alloc.id)
    }

    func count(_ collection: Collection) -> UInt64 { collection.count }

    // MARK: - Tests

    func testEverySaleIsOneBatch() throws {
        struct Injected: Error {}
        store.afterTransactionWrite = { throw Injected() }
        let price = Money(cents: 12900)
        XCTAssertThrowsError(try store.sell(unit: Self.unit, tender: Tender(kind: .cash, amount: price), price: price))
        XCTAssertEqual(count(store.transactions), 0, "the sale rolled back")
        XCTAssertEqual(count(store.allocations), 0)

        // A check-out that would open an allocation: neither the transaction nor the allocation lands.
        XCTAssertThrowsError(try store.checkOut(unit: Self.unit, from: Custodian.store, to: "box-07", actingFor: "box-07"))
        XCTAssertEqual(count(store.transactions), 0)
        XCTAssertEqual(count(store.allocations), 0)

        store.afterTransactionWrite = nil
        let sale = try store.sell(unit: Self.unit, tender: Tender(kind: .cash, amount: price), price: price)
        XCTAssertEqual(count(store.transactions), 1)
        XCTAssertEqual(sale.kind, .sale)
        XCTAssertEqual(sale.fromCustodian, "box-07", "no record: a blind sale off the box")
        XCTAssertNil(sale.prevTxn)
        XCTAssertNil(sale.fromAllocation)
        XCTAssertEqual(sale.toCustodian, Custodian.customer)
        XCTAssertNotNil(sale.basket)
    }

    func testCheckInNeverFailsOnDisagreement() throws {
        // No record at all: from unknown, to the box, no allocation.
        let blind = try store.checkIn(unit: Self.unit)
        XCTAssertEqual(blind.fromCustodian, Custodian.unknown)
        XCTAssertNil(blind.prevTxn)
        XCTAssertEqual(blind.toCustodian, "box-07")
        XCTAssertNil(blind.toAllocation)

        // The record says tablet-b holds the unit (another custodian): the check-in still stands.
        let other = "JKT-RAIN-M-BLU#002"
        let hlc = HLC(ms: 1_792_328_350_000, counter: 0, device: "tablet-b").string
        let take = Transaction(id: "txn::" + hlc, trip: Self.trip, box: "box-07", kind: .checkOut, unitID: other,
                               sku: Ledger.skuOf(other), fromCustodian: "box-07", toCustodian: "tablet-b", prevTxn: nil,
                               fromAllocation: nil, toAllocation: nil, device: "tablet-b", hlc: hlc,
                               deviceClock: "2026-10-18T13:00:00Z")
        try store.save(take, id: take.id, in: store.transactions)
        try store.rebuild()
        let disagreeing = try store.checkIn(unit: other)
        XCTAssertEqual(disagreeing.fromCustodian, "tablet-b")
        XCTAssertEqual(disagreeing.prevTxn, take.id)
        XCTAssertEqual(store.currentState.units[other]?.holder, "box-07", "the movement stands")

        let kinds = try store.detectAndWriteExceptions().map(\.kind)
        XCTAssertEqual(kinds, [.unexpectedCheckIn, .unexpectedCheckIn], "rule 6 flags both")
    }

    func testCheckInReturnsToTheParentAndClosesTheAllocation() throws {
        let pack = try pulledPack()
        try store.rebuild()
        let take = try store.checkOut(unit: Self.unit, from: "box-07", to: "tablet-a")
        XCTAssertEqual(take.prevTxn, pack.id)
        XCTAssertEqual(take.fromAllocation, pack.toAllocation)
        let mine: Allocation = try XCTUnwrap(store.load(id: XCTUnwrap(take.toAllocation), from: store.allocations))
        XCTAssertEqual(mine.parent, pack.toAllocation)
        XCTAssertEqual(mine.status, .active)

        let back = try store.checkIn(unit: Self.unit)
        XCTAssertEqual(back.fromCustodian, "tablet-a")
        XCTAssertEqual(back.toCustodian, "box-07")
        XCTAssertEqual(back.toAllocation, pack.toAllocation)
        XCTAssertEqual(back.prevTxn, take.id)
        let closed: Allocation = try XCTUnwrap(store.load(id: mine.id, from: store.allocations))
        XCTAssertEqual(closed.status, .closed)
        XCTAssertEqual(closed.closedAt, back.hlc)
        XCTAssertEqual(store.currentState.counts[CustodianSKU(custodian: "box-07", sku: "JKT-RAIN-M-BLU")], 1)
        XCTAssertEqual(try store.detectAndWriteExceptions(), [])
    }

    func testHLCAdvancesOnReceive() throws {
        let remote = try pulled(.checkOut, from: Custodian.store, to: "box-07", prev: nil, device: "tablet-b",
                                ms: clock.ms + 60_000)  // tablet-b's clock is a minute ahead
        try store.rebuild()
        let next = try store.checkOut(unit: Self.unit, from: "box-07", to: "tablet-a")
        XCTAssertGreaterThan(HLC(next.hlc)!, HLC(remote.hlc)!)
        XCTAssertEqual(HLC(next.hlc)?.device, "tablet-a")
        XCTAssertEqual(next.prevTxn, remote.id)

        // A fresh store over the same database recovers its clock from what is stored.
        let reopened = try CustodyStore(database: database, identity: store.identity, clock: FakeClock(0))
        let later = try reopened.sell(unit: Self.unit, tender: Tender(kind: .cash, amount: Money(cents: 1)),
                                      price: Money(cents: 1))
        XCTAssertGreaterThan(later.hlc, next.hlc)
    }

    func testDetectAndWriteExceptionsIsIdempotent() throws {
        try pulledPack()
        try store.rebuild()
        let pack = store.currentState.units[Self.unit]!.lastTxn!
        try pulled(.checkOut, from: "box-07", to: "tablet-b", prev: pack, device: "tablet-b", ms: 1_792_328_390_000)
        try store.rebuild()
        // A double take: tablet-a takes from the same pack record.
        try store.save(Transaction(id: "txn::1792328391000-0000-tablet-a", trip: Self.trip, box: "box-07",
                                   kind: .checkOut, unitID: Self.unit, sku: "JKT-RAIN-M-BLU", fromCustodian: "box-07",
                                   toCustodian: "tablet-a", prevTxn: pack, fromAllocation: nil, toAllocation: nil,
                                   device: "tablet-a", hlc: "1792328391000-0000-tablet-a",
                                   deviceClock: "2026-10-18T13:00:00Z"),
                       id: "txn::1792328391000-0000-tablet-a", in: store.transactions)
        try store.rebuild()
        let first = try store.detectAndWriteExceptions()
        XCTAssertEqual(first.map(\.kind), [.doubleScan])
        XCTAssertNotNil(first[0].detectedAt)
        let stored: ExceptionDoc = try XCTUnwrap(store.load(id: first[0].id, from: store.exceptions))
        XCTAssertEqual(stored, first[0])
        XCTAssertEqual(try store.detectAndWriteExceptions(), [])
        XCTAssertEqual(count(store.exceptions), 1)
        XCTAssertEqual(store.currentState.units[Self.unit]?.state, .disputed)
    }

    func testCheckOutWithoutRecordIsABlindTake() throws {
        let take = try store.checkOut(unit: Self.unit, from: "box-07", to: "tablet-a")
        XCTAssertNil(take.prevTxn)
        XCTAssertEqual(take.fromCustodian, "box-07")
        XCTAssertNil(take.fromAllocation)
        XCTAssertNotNil(take.toAllocation)

        try pulledPack()  // the pack arrives, earlier than the take
        try store.rebuild()
        let state = store.currentState
        XCTAssertEqual(state.units[Self.unit]?.holder, "tablet-a")
        XCTAssertEqual(state.units[Self.unit]?.state, .held)
        XCTAssertEqual(state.forks, [])
        XCTAssertEqual(try store.detectAndWriteExceptions(), [])
    }

    func testStatePublisherFollowsWrites() throws {
        var seen: [Int] = []
        let token = store.state.sink { seen.append($0.transactions.count) }
        _ = try store.checkOut(unit: Self.unit, from: Custodian.store, to: "box-07", actingFor: "box-07")
        token.cancel()
        XCTAssertEqual(seen.first, 0)
        XCTAssertEqual(seen.last, 1)
    }

    /// #114: a basket is one batch and one published state. A failure inside the batch (after the first sale was
    /// saved) keeps no sale and publishes nothing; a basket that names a unit twice is refused before any write.
    func testABasketIsOneBatchAndOnePublishedState() throws {
        struct Injected: Error {}
        let pack = try pulledPack()
        try store.rebuild()
        let units = [Self.unit, "JKT-RAIN-M-BLU#002", "HAT-BEANIE-OS#001"]
        let lines = units.map { SaleLine(unit: $0, price: Money(cents: 12900)) }
        let tender = Tender(kind: .cardSimulated, amount: Money(cents: 38700))
        var published: [Int] = []
        let token = store.state.dropFirst().sink { published.append($0.transactions.values.filter { $0.kind == .sale }.count) }
        defer { token.cancel() }

        var writes = 0
        store.afterTransactionWrite = {
            writes += 1
            if writes == 2 { throw Injected() }
        }
        XCTAssertThrowsError(try store.sell(basket: lines, tender: tender))
        XCTAssertEqual(writes, 2, "the failure is inside the batch, after one sale was saved")
        XCTAssertEqual(count(store.transactions), 1, "only the pulled pack: the basket rolled back")
        XCTAssertEqual(published, [], "nothing published for a basket that did not commit")

        XCTAssertThrowsError(try store.sell(basket: lines + [lines[0]], tender: tender)) { error in
            XCTAssertEqual(error as? CustodyStore.Failure, .sameUnitTwice)
        }
        XCTAssertEqual(count(store.transactions), 1)

        store.afterTransactionWrite = nil
        let sales = try store.sell(basket: lines, tender: tender, id: "5b0c1c55-63a1-4a4e-9c3f-0e6d7b8a9f10")
        XCTAssertEqual(count(store.transactions), 4)
        XCTAssertEqual(published, [3], "one state, with the whole basket in it")
        XCTAssertEqual(sales.map(\.unitID), units)
        XCTAssertTrue(sales.allSatisfy { $0.basket == "5b0c1c55-63a1-4a4e-9c3f-0e6d7b8a9f10" && $0.tender == tender })
        XCTAssertEqual(sales[0].prevTxn, pack.id, "the packed unit continues its chain")
        XCTAssertEqual(sales[0].fromCustodian, "box-07")
        XCTAssertEqual(Set(sales.map(\.id)).count, 3, "each sale has its own hlc")
        XCTAssertTrue(units.allSatisfy { store.currentState.units[$0]?.state == .sold })
    }

    // MARK: - Rule 0: drop, never skip (decision 010)

    /// A body saved as Couchbase Lite holds it (no `_id`), edited after encoding: what a peer on another schema, or
    /// a bug, would push.
    @discardableResult
    func pulledRaw(_ txn: Transaction, edit: (inout [String: Any]) -> Void) throws -> String {
        let encoder = JSONEncoder()
        encoder.userInfo[.omitDocumentID] = true
        var body = try JSONSerialization.jsonObject(with: encoder.encode(txn)) as! [String: Any]
        edit(&body)
        let json = String(decoding: try JSONSerialization.data(withJSONObject: body), as: UTF8.self)
        if let existing = try store.transactions.document(id: txn.id) {
            try store.transactions.save(document: existing.toMutable().setJSON(json))
        } else {
            try store.transactions.save(document: MutableDocument(id: txn.id, json: json))
        }
        return txn.id
    }

    func take(ms: Int64, device: String = "tablet-b", prev: String? = nil) -> Transaction {
        let hlc = HLC(ms: ms, counter: 0, device: device).string
        return Transaction(id: "txn::" + hlc, trip: Self.trip, box: "box-07", kind: .checkOut, unitID: Self.unit,
                           sku: Ledger.skuOf(Self.unit), fromCustodian: "box-07", toCustodian: device, prevTxn: prev,
                           fromAllocation: nil, toAllocation: nil, device: device, hlc: hlc,
                           deviceClock: "2026-10-18T13:00:00Z")
    }

    func logEntries() throws -> [DropRecord] { try store.dropLog.entries() }

    func testInvalidDocumentIsDroppedNotSkipped() throws {
        let pack = try pulledPack()
        let bad = try pulledRaw(take(ms: 1_792_328_500_000, prev: pack.id)) { $0["kind"] = "transfer" }
        var published: [[DropRecord]] = []
        let token = store.drops.sink { published.append($0) }
        defer { token.cancel() }
        let state = try store.rebuild()

        XCTAssertNil(state.transactions[bad], "the dropped take is not reduced")
        XCTAssertNotNil(state.transactions[pack.id])
        XCTAssertEqual(state.units[Self.unit]?.holder, "box-07", "the unit is where the pack left it")
        let drops = store.currentDrops
        XCTAssertEqual(drops.map(\.id), [bad])
        XCTAssertEqual(drops.first?.collection, "transaction")
        XCTAssertEqual(drops.first?.code, .invalidValue)
        XCTAssertEqual(drops.first?.source, "peer")
        XCTAssertEqual(drops.first?.firstSeen, "2026-10-18T13:00:00.000Z")
        XCTAssertTrue(drops.first?.detail.contains("transfer") ?? false)
        XCTAssertEqual(published.last, drops, "published after the rebuild")

        let logged = try XCTUnwrap(try store.dropLog.collection.document(id: DropRecord.key(collection: "transaction", id: bad)))
        XCTAssertEqual(logged.string(forKey: "id"), bad)
        XCTAssertEqual(logged.string(forKey: "code"), "invalid_value")
        XCTAssertEqual(logged.string(forKey: "source"), "peer")
        XCTAssertEqual(try logEntries(), drops)
        XCTAssertEqual(store.dropLog.collection.scope.name, CustodyStore.localScope, "never replicated")
        XCTAssertFalse(CustodyStore.replicatedCollections.contains("drop_log"))

        // Fixed (a valid revision under the same id): reduced again, and no longer counted.
        try pulledRaw(take(ms: 1_792_328_500_000, prev: pack.id)) { _ in }
        try store.rebuild()
        XCTAssertNotNil(store.currentState.transactions[bad])
        XCTAssertEqual(store.currentDrops, [])
        XCTAssertEqual(try logEntries().count, 1, "the log keeps the entry")
    }

    func testVersionTwoIsDroppedAsVersion() throws {
        let id = try pulledRaw(take(ms: 1_792_328_500_000)) { $0["v"] = 2 }
        try store.rebuild()
        XCTAssertEqual(store.currentDrops.map(\.code), [.version])
        XCTAssertEqual(store.currentDrops.map(\.id), [id])
        XCTAssertEqual(store.currentDrops.first?.code.words, "newer schema: update the app")
    }

    func testSourceIsLocalWhenTheIDNamesThisDeviceAndBoxWhenPulled() throws {
        let mine = try pulledRaw(take(ms: 1_792_328_500_000, device: "tablet-a")) { $0["note"] = "edited" }
        let boxed = try pulledRaw(take(ms: 1_792_328_600_000)) { $0["note"] = "edited" }
        let peer = try pulledRaw(take(ms: 1_792_328_700_000)) { $0["note"] = "edited" }
        store.pulledFromBox = { $0 == boxed }
        try store.rebuild()
        let sources = Dictionary(uniqueKeysWithValues: store.currentDrops.map { ($0.id, $0.source) })
        XCTAssertEqual(sources, [mine: "local", boxed: "box", peer: "peer"])
        XCTAssertTrue(store.currentDrops.allSatisfy { $0.code == .extraField })
    }

    func testDropLogIsBoundedAndKeyed() throws {
        try database.inBatch {  // one change notification, not 250
            for i in 0..<250 {
                try pulledRaw(take(ms: 1_792_328_500_000 + Int64(i) * 1000)) { $0["kind"] = "transfer" }
            }
        }
        try store.rebuild()
        XCTAssertEqual(try logEntries().count, 200, "at most 200 entries")
        XCTAssertEqual(store.currentDrops.count, 250, "every drop is counted, stored or not")
        let held = Set(try logEntries().map(\.id))

        // Again: nothing churns, and the entries the log holds are the same ones.
        clock.advance(60_000)
        try store.rebuild()
        XCTAssertEqual(Set(try logEntries().map(\.id)), held)
        XCTAssertTrue(try logEntries().allSatisfy { $0.firstSeen == "2026-10-18T13:00:00.000Z" && $0.lastSeen == "2026-10-18T13:01:00.000Z" })

        // Re-saving one updates lastSeen only; one entry per (collection, id).
        let resaved = try XCTUnwrap(held.sorted().first)
        clock.advance(60_000)
        try pulledRaw(take(ms: Int64(HLC(String(resaved.dropFirst(5)))!.ms))) { $0["kind"] = "transfer" }
        try store.rebuild()
        let entry = try XCTUnwrap(try logEntries().first { $0.id == resaved })
        XCTAssertEqual(entry.firstSeen, "2026-10-18T13:00:00.000Z")
        XCTAssertEqual(entry.lastSeen, "2026-10-18T13:02:00.000Z")
        XCTAssertEqual(try logEntries().filter { $0.id == resaved }.count, 1)

        // Older entries go first: once 200 newer drops arrive, the old ones are evicted.
        let fresh = DropLog(database: database, collection: store.dropLog.collection)
        let later = (0..<200).map { Drop(id: "txn::later-\($0)", collection: "transaction", code: .rule, detail: "x") }
        _ = try fresh.record(later, now: "2026-10-18T14:00:00.000Z") { _ in "peer" }
        XCTAssertEqual(Set(try logEntries().map(\.id)), Set(later.map(\.id)))
    }

    // MARK: - Gate findings on #189: a dropped document never stops the ledger or refuses a scan

    /// Gate finding 1: a dropped document's id longer than the drop log could key (Couchbase Lite ids are at most
    /// 240 bytes) used to make `rebuild()` throw. Ids of 227, 228 and 240 bytes in both collections are saved into
    /// the real database; a 1000-byte id (which Couchbase Lite itself refuses to store) goes through the log.
    func testLongIDsNeverWedgeTheRebuild() throws {
        var saved = 0
        for length in [227, 228, 240] {
            for (collection, prefix) in [(store.transactions, "txn::"), (store.exceptions, "exc::")] {
                let id = prefix + String(repeating: "x", count: length - prefix.utf8.count)
                XCTAssertEqual(id.utf8.count, length)
                try collection.save(document: MutableDocument(id: id, json: #"{"type": "nonsense"}"#))
                saved += 1
            }
        }
        XCTAssertNoThrow(try store.rebuild())
        XCTAssertEqual(store.currentDrops.count, saved, "every one counted")
        XCTAssertTrue(store.currentDrops.allSatisfy { $0.code == .wrongType })
        XCTAssertEqual(Set(try logEntries().map(\.id)), Set(store.currentDrops.map(\.id)), "and logged, by their real ids")

        let take = try store.checkOut(unit: "HAT-BEANIE-OS#001", from: "box-07", to: "tablet-a")
        XCTAssertNotNil(store.currentState.transactions[take.id], "a scan of another unit commits and is reduced")
        store = nil
        store = try CustodyStore(database: database, identity: DeviceIdentity(device: "tablet-a", box: "box-07",
                                                                              trip: Self.trip), clock: clock)
        XCTAssertEqual(store.currentDrops.count, saved, "the app starts on this database")

        let long = Drop(id: "txn::" + String(repeating: "y", count: 995), collection: "transaction", code: .rule, detail: "x")
        XCTAssertThrowsError(try store.transactions.save(document: MutableDocument(id: long.id, json: "{}")),
                             "Couchbase Lite refuses a 1000-byte id, so only a log entry can carry one")
        let recorded = store.dropLog.record([long], now: "2026-10-18T14:00:00.000Z") { _ in "peer" }
        XCTAssertEqual(recorded.map(\.id), [long.id])
        XCTAssertTrue(try logEntries().contains { $0.id == long.id }, "the entry is stored under a bounded key")
        XCTAssertLessThanOrEqual(DropRecord.key(collection: "exception", id: long.id).utf8.count, 240)
    }

    /// Nothing the log does fails a rebuild: a write that throws leaves the drops counted and published, and the
    /// failure is logged once.
    func testDropLogFailureNeverFailsTheRebuild() throws {
        struct Injected: Error {}
        let bad = try pulledRaw(take(ms: 1_792_328_500_000)) { $0["v"] = 2 }
        store.dropLog.beforeWrite = { throw Injected() }
        XCTAssertNoThrow(try store.rebuild())
        XCTAssertNoThrow(try store.rebuild())
        XCTAssertEqual(store.currentDrops.map(\.id), [bad])
        XCTAssertEqual(store.dropLog.failuresLogged.count, 1, "logged once, not on every rebuild")
        XCTAssertEqual(try logEntries(), [], "the write rolled back")
        store.dropLog.beforeWrite = nil
        try store.rebuild()
        XCTAssertEqual(try logEntries().map(\.id), [bad], "and the next good write stores it")
    }

    /// Gate finding 2: when the movement a unit's record names is replaced by an invalid revision, the unit is one
    /// this device does not know: scans and sales of it still succeed (blind), never a DecodingError.
    func testAUnitWhoseLatestMovementIsDroppedCanStillBeScannedAndSold() throws {
        let pack = try pulledPack()
        try store.rebuild()
        XCTAssertEqual(store.currentState.units[Self.unit]?.holder, "box-07")
        try pulledRaw(pack) { $0["kind"] = "transfer" }

        // Before any rebuild (the window between a pull and its change notification): still no refusal.
        let early = try store.checkOut(unit: Self.unit, from: "box-07", to: "tablet-a")
        XCTAssertNil(early.prevTxn, "the dropped pack is not a predecessor")
        XCTAssertEqual(store.currentDrops.map(\.id), [pack.id])

        let price = Money(cents: 12900)
        let sale = try store.sell(unit: "JKT-RAIN-M-BLU#002", tender: Tender(kind: .cash, amount: price), price: price)
        XCTAssertEqual(store.currentState.units["JKT-RAIN-M-BLU#002"]?.state, .sold)
        XCTAssertNotNil(store.currentState.transactions[sale.id])
        XCTAssertEqual(store.currentState.units[Self.unit]?.holder, "tablet-a")
    }

    func testAStaleRecordIsRemovedAndComesBackWithAValidRevision() throws {
        let pack = try pulledPack()
        try store.rebuild()
        try pulledRaw(pack) { $0["kind"] = "transfer" }
        try store.rebuild()
        XCTAssertNil(store.currentState.units[Self.unit])
        XCTAssertNil(try store.unitStates.document(id: Self.unit), "no record for a unit the state does not have")
        let price = Money(cents: 12900)
        let sale = try store.sell(unit: Self.unit, tender: Tender(kind: .cash, amount: price), price: price)
        XCTAssertNil(sale.prevTxn, "a blind sale from the box, which rule 1 links")
        XCTAssertEqual(sale.fromCustodian, "box-07")

        // The pack gets a valid revision again: the unit is known through it, and the sale continues it.
        try pulledRaw(pack) { _ in }
        try store.rebuild()
        XCTAssertEqual(store.currentDrops, [])
        XCTAssertEqual(store.currentState.units[Self.unit]?.state, .sold)
        XCTAssertNotNil(try store.unitStates.document(id: Self.unit))
        let returned = try store.checkIn(unit: Self.unit)
        XCTAssertEqual(returned.prevTxn, sale.id)
    }

    /// Gate finding 3: ids that differ only by Unicode normalisation are two Couchbase Lite documents and two drops
    /// (as in the reference), and a key that is `_` followed by a combining mark is metadata.
    func testIDsAndKeysAreComparedByCodePoint() throws {
        for id in ["txn::\u{e9}", "txn::e\u{301}"] {
            try store.transactions.save(document: MutableDocument(id: id, json: #"{"type": "nonsense"}"#))
        }
        XCTAssertEqual(store.transactions.count, 2)
        let pack = try pulledRaw(take(ms: 1_792_328_500_000)) { $0["_\u{301}x"] = 1 }
        try store.rebuild()
        XCTAssertEqual(store.currentDrops.count, 2)
        XCTAssertEqual(try logEntries().count, 2)
        XCTAssertNotNil(store.currentState.transactions[pack], "the _-key is ignored, the movement reduced")
    }

    func testPairingPayloadDecodesPortExample() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "box-agent", withExtension: "md"))
        let doc = try String(contentsOf: url, encoding: .utf8)
        let section = try XCTUnwrap(doc.range(of: "### Pairing payload"))
        let start = try XCTUnwrap(doc.range(of: "```json\n", range: section.upperBound..<doc.endIndex))
        let end = try XCTUnwrap(doc.range(of: "```", range: start.upperBound..<doc.endIndex))
        let payload = try PairingPayload.decode(String(doc[start.upperBound..<end.lowerBound]))
        XCTAssertEqual(payload.v, 1)
        XCTAssertEqual(payload.device, "tablet-a")
        XCTAssertEqual(payload.box, "box-07")
        XCTAssertEqual(payload.trip, Self.trip)
        XCTAssertEqual(payload.edgeURL, "ws://192.0.2.10:59840/retail")
        XCTAssertNil(payload.certSHA256)
        XCTAssertEqual(payload.peerGroup, "siab-trip-2026-10-18-riverfest")
        XCTAssertEqual(payload.identity, DeviceIdentity(device: "tablet-a", box: "box-07", trip: Self.trip))
        XCTAssertEqual(payload.agentURL?.absoluteString, "http://192.0.2.10:8787")

        var future = try JSONSerialization.jsonObject(with: Data(doc[start.upperBound..<end.lowerBound].utf8)) as! [String: Any]
        future["v"] = 2
        let text = String(decoding: try JSONSerialization.data(withJSONObject: future), as: UTF8.self)
        XCTAssertThrowsError(try PairingPayload.decode(text)) { error in
            XCTAssertEqual(error as? PairingPayload.Error, .unsupportedVersion(2))
        }
    }
}
