import SIABCore
import XCTest
@testable import StoreInABox

@MainActor
final class ShelfViewModelTests: XCTestCase {
    func testRowsFollowLedgerState() throws {
        let store = FakeCustodyStore()
        let catalog = FakeCatalog([TestData.rainShell, TestData.beanie])
        let model = ShelfViewModel(store: store, catalog: catalog)
        func row(_ sku: String) -> ShelfRow? { model.rows.first { $0.sku == sku } }

        XCTAssertEqual(model.rows.map(\.sku), ["HAT-BEANIE-OS", "JKT-RAIN-M-BLU"], "every catalog product, by SKU")
        XCTAssertEqual(row("JKT-RAIN-M-BLU"), ShelfRow(sku: "JKT-RAIN-M-BLU", name: "Rain shell",
                                                       price: Money(cents: 12900), here: 0, box: 0))

        var packs: [String: Transaction] = [:]
        for serial in ["001", "002", "003"] {
            let unit = "JKT-RAIN-M-BLU#" + serial
            packs[unit] = store.pull(.checkOut, unit, from: Custodian.store, to: "box-07", device: "tablet-b")
        }
        XCTAssertEqual(row("JKT-RAIN-M-BLU")?.box, 3, "a pack on another tablet moves the box count")

        let take = try store.checkOut(unit: "JKT-RAIN-M-BLU#001", from: "box-07", to: "tablet-a", actingFor: nil)
        XCTAssertEqual(row("JKT-RAIN-M-BLU").map { [$0.here, $0.box] }, [1, 2])

        store.pull(.checkOut, "JKT-RAIN-M-BLU#002", from: "box-07", to: "tablet-b", device: "tablet-b",
                   prev: packs["JKT-RAIN-M-BLU#002"]!.id)
        XCTAssertEqual(row("JKT-RAIN-M-BLU").map { [$0.here, $0.box] }, [1, 1], "another tablet's take: the box drops")

        try store.sell(unit: "JKT-RAIN-M-BLU#001", tender: Tender(kind: .cash, amount: Money(cents: 12900)),
                       price: Money(cents: 12900), basket: UUID().uuidString.lowercased())
        XCTAssertEqual(row("JKT-RAIN-M-BLU").map { [$0.here, $0.box] }, [0, 1], "a sale here: here drops")
        XCTAssertEqual(store.written.first?.id, take.id)

        store.pull(.checkOut, "PCK-COVER-M#001", from: Custodian.store, to: "box-07", device: "tablet-b")
        XCTAssertEqual(row("PCK-COVER-M"), ShelfRow(sku: "PCK-COVER-M", name: "PCK-COVER-M", price: nil, here: 0, box: 1),
                       "a SKU in the ledger but not the catalog still gets a row")

        catalog.subject.send([TestData.rainShell.sku: TestData.rainShell])
        XCTAssertEqual(model.rows.map(\.sku), ["JKT-RAIN-M-BLU", "PCK-COVER-M"], "the catalog is followed too")

        model.filter = "rain"
        XCTAssertEqual(model.rows.map(\.sku), ["JKT-RAIN-M-BLU"], "the filter matches the name or the SKU")
        model.filter = "cover"
        XCTAssertEqual(model.rows.map(\.sku), ["PCK-COVER-M"])
        model.filter = ""
        XCTAssertEqual(model.rows.count, 2)
    }
}
