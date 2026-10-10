import SIABCore
import XCTest
@testable import StoreInABox

@MainActor
final class SellViewModelTests: XCTestCase {
    var store: FakeCustodyStore!
    var scheduler: FakeScheduler!
    var model: SellViewModel!

    override func setUp() {
        store = FakeCustodyStore()
        scheduler = FakeScheduler()
        model = SellViewModel(store: store, catalog: FakeCatalog([TestData.rainShell, TestData.beanie]),
                              scheduler: scheduler)
    }

    /// What a scan of a rain shell says: integer cents divided by 100 (decision 003), in the device's locale.
    let shell = "Rain shell " + Decimal(129).formatted(.currency(code: "USD"))

    func testBasketRejectsDuplicateUnit() {
        XCTAssertEqual(model.add(scan: TestData.scan("JKT-RAIN-M-BLU#001")), .success(shell))
        XCTAssertEqual(model.add(scan: TestData.scan("JKT-RAIN-M-BLU#001")), .failure(.sameUnitTwice("JKT-RAIN-M-BLU#001")))
        XCTAssertEqual(ScanRejection.sameUnitTwice("JKT-RAIN-M-BLU#001").reason,
                       "JKT-RAIN-M-BLU#001 is already in this basket")
        XCTAssertEqual(model.add(scan: TestData.scan("JKT-RAIN-M-BLU#002")), .success(shell),
                       "another unit of the same SKU is a new line")
        XCTAssertEqual(model.basket.map(\.unit), ["JKT-RAIN-M-BLU#001", "JKT-RAIN-M-BLU#002"])
        model.remove(unit: "JKT-RAIN-M-BLU#001")
        XCTAssertEqual(model.basket.map(\.unit), ["JKT-RAIN-M-BLU#002"])
    }

    func testTenderSellsEveryLineWithOneBasketId() throws {
        for unit in ["JKT-RAIN-M-BLU#001", "JKT-RAIN-M-BLU#002", "HAT-BEANIE-OS#001"] {
            store.pull(.checkOut, unit, from: Custodian.store, to: "box-07", device: "tablet-b")
            model.add(scan: TestData.scan(unit))
        }
        XCTAssertEqual(model.total, Money(cents: 28250))

        try model.tender(kind: .card_simulated)

        XCTAssertEqual(store.batches, 1, "one batch for the whole basket")
        let sales = store.written
        XCTAssertEqual(sales.map(\.unitID), ["JKT-RAIN-M-BLU#001", "JKT-RAIN-M-BLU#002", "HAT-BEANIE-OS#001"])
        XCTAssertTrue(sales.allSatisfy { $0.kind == .sale && $0.toCustodian == Custodian.customer })
        let baskets = Set(sales.compactMap(\.basket))
        XCTAssertEqual(baskets.count, 1, "one basket id on every sale")
        XCTAssertNotNil(baskets.first?.wholeMatch(of: #/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/#),
                        "a lower-case UUID, as the schema's pattern requires")
        XCTAssertEqual(sales.map(\.price), [Money(cents: 12900), Money(cents: 12900), Money(cents: 2450)])
        XCTAssertTrue(sales.allSatisfy { $0.tender == Tender(kind: .cardSimulated, amount: Money(cents: 28250)) })

        XCTAssertTrue(model.basket.isEmpty)
        XCTAssertEqual(model.confirmation, SaleConfirmation(count: 3, total: Money(cents: 28250)))
        scheduler.advance(1.9)
        XCTAssertNotNil(model.confirmation, "shown for two seconds")
        scheduler.advance(0.1)
        XCTAssertNil(model.confirmation)
        XCTAssertEqual(store.currentState.units["HAT-BEANIE-OS#001"]?.state, .sold)
    }

    func testFailedTenderWritesNothingAndKeepsTheBasket() {
        model.add(scan: TestData.scan("JKT-RAIN-M-BLU#001"))
        model.add(scan: TestData.scan("JKT-RAIN-M-BLU#002"))
        store.failNextSell = true
        XCTAssertThrowsError(try model.tender(kind: .cash))
        XCTAssertTrue(store.written.isEmpty)
        XCTAssertEqual(model.basket.count, 2)
        XCTAssertNil(model.confirmation)
        let empty = SellViewModel(store: FakeCustodyStore(), catalog: FakeCatalog([]))
        XCTAssertThrowsError(try empty.tender(kind: .cash)) { XCTAssertEqual($0 as? SellError, .emptyBasket) }
    }

    /// Rule 8: a sale of a unit another tablet holds is foreign. The scan is accepted, tagged, and sold.
    func testSaleOfAUnitAnotherDeviceHoldsIsAcceptedAndTagged() throws {
        let pack = store.pull(.checkOut, "JKT-RAIN-M-BLU#003", from: Custodian.store, to: "box-07", device: "tablet-b")
        store.pull(.checkOut, "JKT-RAIN-M-BLU#003", from: "box-07", to: "tablet-b", device: "tablet-b", prev: pack.id)
        store.pull(.checkOut, "JKT-RAIN-M-BLU#004", from: Custodian.store, to: "box-07", device: "tablet-b")

        XCTAssertEqual(model.add(scan: TestData.scan("JKT-RAIN-M-BLU#003")), .success(shell))
        model.add(scan: TestData.scan("JKT-RAIN-M-BLU#004"))
        XCTAssertEqual(model.basket.map(\.disagrees), [true, false], "held by tablet-b: tagged; held by the box: not")

        try model.tender(kind: .cash)
        let kinds = Ledger.exceptions(for: store.currentState, detector: "tablet-a", trip: TestData.trip, box: "box-07")
            .map(\.kind)
        XCTAssertEqual(kinds, [.foreignMovement], "the ledger flags it; the sale stands")
    }

    func testUnknownSKUIsRefused() {
        XCTAssertEqual(model.add(scan: TestData.scan("PCK-DAY-20#001")), .failure(.unknownSKU("PCK-DAY-20")))
        XCTAssertTrue(model.basket.isEmpty)
    }
}
