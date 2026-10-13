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

    /// The failure is injected at `beforeBatchCommit`, after the transaction and the allocations are saved, so a
    /// `commit` split into two batches leaves the first one's documents behind and fails here (#104 item 1). The hook
    /// also records what the batch had saved when it ran, which pins the seam after the allocation saves.
    func testEverySaleIsOneBatch() throws {
        struct Injected: Error {}
        var inBatch: [(transactions: UInt64, allocations: UInt64)] = []
        let (transactions, allocations) = (store.transactions, store.allocations)
        store.beforeBatchCommit = {
            inBatch.append((transactions.count, allocations.count))
            throw Injected()
        }
        let price = Money(cents: 12900)
        XCTAssertThrowsError(try store.sell(unit: Self.unit, tender: Tender(kind: .cash, amount: price), price: price))
        XCTAssertEqual(inBatch.last?.transactions, 1, "the sale was saved inside the batch")
        XCTAssertEqual(count(store.transactions), 0, "the sale rolled back")
        XCTAssertEqual(count(store.allocations), 0)

        // A check-out that opens an allocation: both were saved in the batch, and neither lands.
        XCTAssertThrowsError(try store.checkOut(unit: Self.unit, from: Custodian.store, to: "box-07", actingFor: "box-07"))
        XCTAssertEqual(inBatch.last?.transactions, 1)
        XCTAssertEqual(inBatch.last?.allocations, 1, "the allocation was saved before the hook ran")
        XCTAssertEqual(count(store.transactions), 0)
        XCTAssertEqual(count(store.allocations), 0)

        // A check-in that closes this device's allocation: the close rolls back with the movement.
        store.beforeBatchCommit = nil
        try pulledPack()
        try store.rebuild()
        let take = try store.checkOut(unit: Self.unit, from: "box-07", to: "tablet-a")
        let mine = try XCTUnwrap(take.toAllocation)
        let before = count(store.transactions)
        store.beforeBatchCommit = { throw Injected() }
        XCTAssertThrowsError(try store.checkIn(unit: Self.unit))
        XCTAssertEqual(count(store.transactions), before, "the check-in rolled back")
        let kept: Allocation = try XCTUnwrap(store.load(id: mine, from: store.allocations))
        XCTAssertEqual(kept.status, .active, "and so did the allocation it closed")
        XCTAssertEqual(store.currentState.units[Self.unit]?.holder, "tablet-a")

        store.beforeBatchCommit = nil
        let other = "JKT-RAIN-M-BLU#002"
        let sale = try store.sell(unit: other, tender: Tender(kind: .cash, amount: price), price: price)
        XCTAssertEqual(count(store.transactions), before + 1)
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

    /// #50 (owner ruling, WS4 Rules): the app never writes `product` or `trip`; Edge Server cannot restrict a device
    /// to some collections, so this test is the guard. Every CustodyStore write operation runs (each kind of check-out,
    /// check-in and sale, a basket, a write that fails inside its batch, exception detection and a rebuild) with one
    /// product and one trip already pulled; neither collection gains, changes or loses a document, and neither
    /// reports a change.
    func testNoWriteTouchesProductOrTrip() throws {
        struct Injected: Error {}
        let product = try XCTUnwrap(database.collection(name: "product", scope: CustodyStore.storeScope))
        let trip = try XCTUnwrap(database.collection(name: "trip", scope: CustodyStore.storeScope))
        try product.save(document: MutableDocument(id: "JKT-RAIN-M-BLU", json: """
            {"type":"product","v":1,"sku":"JKT-RAIN-M-BLU","name":"Rain shell","price":{"cents":12900}}
            """))
        try trip.save(document: MutableDocument(id: Self.trip, json: """
            {"type":"trip","v":1,"trip":"\(Self.trip)","name":"Richmond Riverfest"}
            """))
        let revisions = try [product.document(id: "JKT-RAIN-M-BLU")?.revisionID, trip.document(id: Self.trip)?.revisionID]
        var changed: [String] = []
        let tokens = [product, trip].map { collection in
            collection.addChangeListener(queue: .main) { change in
                changed += change.documentIDs.map { "\(collection.name)/\($0)" }
            }
        }
        defer { tokens.forEach { $0.remove() } }

        let price = Money(cents: 12900)
        let cash = Tender(kind: .cash, amount: price)
        try store.checkOut(unit: Self.unit, from: Custodian.store, to: "box-07", actingFor: "box-07")  // pack
        try store.checkOut(unit: Self.unit, from: "box-07", to: "tablet-a")                          // take
        try store.checkIn(unit: Self.unit)                                     // back, closing the allocation
        try store.checkOut(unit: "JKT-RAIN-M-BLU#002", from: "box-07", to: "tablet-a")  // a blind take
        try store.checkIn(unit: "HAT-BEANIE-OS#001")                           // no record: from unknown
        try store.sell(unit: Self.unit, tender: cash, price: price)            // off the box
        try store.sell(unit: "JKT-RAIN-M-BLU#002", tender: cash, price: price)  // from this device
        try store.sell(basket: ["JKT-RAIN-M-BLU#003", "HAT-BEANIE-OS#002"].map { SaleLine(unit: $0, price: price) },
                       tender: Tender(kind: .cardSimulated, amount: Money(cents: 25800)))
        try store.sell(unit: Self.unit, tender: cash, price: price)            // a unit already sold
        XCTAssertThrowsError(try store.sell(basket: [SaleLine(unit: Self.unit, price: price)] + [SaleLine(unit: Self.unit, price: price)],
                                            tender: cash))                     // refused before any write
        store.beforeBatchCommit = { throw Injected() }
        XCTAssertThrowsError(try store.checkOut(unit: "JKT-RAIN-M-BLU#004", from: Custodian.store, to: "box-07",
                                                actingFor: "box-07"))         // rolled back
        store.beforeBatchCommit = nil
        let exceptions = try store.detectAndWriteExceptions()
        try store.rebuild()

        XCTAssertGreaterThanOrEqual(count(store.transactions), 9, "the writes landed")
        XCTAssertGreaterThanOrEqual(count(store.allocations), 2)
        XCTAssertFalse(exceptions.isEmpty, "exception detection wrote documents")
        let drained = expectation(description: "change notifications delivered")
        DispatchQueue.main.async { drained.fulfill() }
        wait(for: [drained], timeout: 10)
        XCTAssertEqual(changed, [], "no change to store.product or store.trip")
        XCTAssertEqual(product.count, 1)
        XCTAssertEqual(trip.count, 1)
        XCTAssertEqual(try [product.document(id: "JKT-RAIN-M-BLU")?.revisionID, trip.document(id: Self.trip)?.revisionID],
                       revisions)
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
