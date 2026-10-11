import SIABCore
import XCTest
@testable import StoreInABox

@MainActor
final class CustodyViewModelTests: XCTestCase {
    var store: FakeCustodyStore!
    var model: CustodyViewModel!

    override func setUp() {
        store = FakeCustodyStore()
        model = CustodyViewModel(store: store)
    }

    func testHeadersNameTheMode() {
        XCTAssertEqual(model.header, "TAKING FROM box-07")
        model.mode = .return_
        XCTAssertEqual(model.header, "RETURNING TO box-07")
        model.mode = .pack
        XCTAssertEqual(model.header, "PACKING store-richmond → box-07")
    }

    func testPackActsForBox() throws {
        model.mode = .pack
        try model.apply(scan: TestData.scan("JKT-RAIN-M-BLU#001"))

        XCTAssertEqual(store.calls, [.init(name: "checkOut", unit: "JKT-RAIN-M-BLU#001", from: Custodian.store,
                                           to: "box-07", actingFor: "box-07")])
        let line = try XCTUnwrap(model.session.first)
        XCTAssertFalse(line.disagrees, "no record yet: the first scan out of the store")
        XCTAssertEqual(line.allocation, store.written.first?.toAllocation, "the box's allocation it fills")
        XCTAssertEqual(line.allocationHolder, "box-07")
        XCTAssertEqual(store.currentState.counts[CustodianSKU(custodian: "box-07", sku: "JKT-RAIN-M-BLU")], 1)
    }

    func testTakeChecksOutFromTheBoxOntoThisDevice() throws {
        store.pull(.checkOut, "JKT-RAIN-M-BLU#001", from: Custodian.store, to: "box-07", device: "tablet-b")
        try model.apply(scan: TestData.scan("JKT-RAIN-M-BLU#001"))

        XCTAssertEqual(store.calls.first, .init(name: "checkOut", unit: "JKT-RAIN-M-BLU#001", from: "box-07",
                                                to: "tablet-a", actingFor: nil))
        XCTAssertEqual(model.session.map(\.disagrees), [false])
        XCTAssertEqual(store.currentState.counts[CustodianSKU(custodian: "tablet-a", sku: "JKT-RAIN-M-BLU")], 1)
    }

    /// Rule 6: a return of a unit this device did not hold, or has no record of, is accepted, tagged and written;
    /// the ledger raises the unexpected check-in.
    func testReturnOfDisagreeingUnitIsAcceptedAndTagged() throws {
        let pack = store.pull(.checkOut, "JKT-RAIN-M-BLU#002", from: Custodian.store, to: "box-07", device: "tablet-b")
        store.pull(.checkOut, "JKT-RAIN-M-BLU#002", from: "box-07", to: "tablet-b", device: "tablet-b", prev: pack.id)
        model.mode = .return_

        try model.apply(scan: TestData.scan("JKT-RAIN-M-BLU#002"))  // tablet-b holds it
        try model.apply(scan: TestData.scan("JKT-RAIN-M-BLU#009"))  // no record at all

        XCTAssertEqual(model.session.map(\.unit), ["JKT-RAIN-M-BLU#009", "JKT-RAIN-M-BLU#002"], "newest first")
        XCTAssertEqual(model.session.map(\.disagrees), [true, true])
        XCTAssertEqual(store.written.map(\.kind), [.checkIn, .checkIn], "both movements stand")
        XCTAssertEqual(store.written.map(\.fromCustodian), ["tablet-b", Custodian.unknown])
        let exceptions = ExceptionsViewModel.disputes(state: store.currentState, identity: store.identity)
        XCTAssertEqual(exceptions.map(\.kind), [.unexpectedCheckIn, .unexpectedCheckIn])
    }

    func testReturnOfAUnitThisDeviceHoldsEmptiesItsAllocation() throws {
        store.pull(.checkOut, "JKT-RAIN-M-BLU#003", from: Custodian.store, to: "box-07", device: "tablet-b")
        try model.apply(scan: TestData.scan("JKT-RAIN-M-BLU#003"))  // take
        let filled = model.session.first?.allocation
        model.mode = .return_
        try model.apply(scan: TestData.scan("JKT-RAIN-M-BLU#003"))

        XCTAssertEqual(model.session.first?.mode, .return_)
        XCTAssertEqual(model.session.first?.disagrees, false)
        XCTAssertNotNil(filled)
        XCTAssertEqual(model.session.first?.allocation, filled, "the return empties the allocation the take filled")
        XCTAssertEqual(model.session.map(\.allocationHolder), ["tablet-a", "tablet-a"])
    }

    /// A take of a unit another tablet holds: accepted with the tag, never refused.
    func testTakeOfAUnitAnotherDeviceHoldsIsTagged() {
        let pack = store.pull(.checkOut, "JKT-RAIN-M-BLU#004", from: Custodian.store, to: "box-07", device: "tablet-b")
        store.pull(.checkOut, "JKT-RAIN-M-BLU#004", from: "box-07", to: "tablet-b", device: "tablet-b", prev: pack.id)

        XCTAssertEqual(model.handle(scan: TestData.scan("JKT-RAIN-M-BLU#004")), .success("Take: JKT-RAIN-M-BLU#004"))
        XCTAssertEqual(model.session.map(\.disagrees), [true])
        model.clearSession()
        XCTAssertTrue(model.session.isEmpty)
    }
}
