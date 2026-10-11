import SIABCore
import XCTest
@testable import StoreInABox

@MainActor
final class ExceptionsViewModelTests: XCTestCase {
    var store: FakeCustodyStore!
    var model: ExceptionsViewModel!

    override func setUp() {
        store = FakeCustodyStore()
        model = ExceptionsViewModel(store: store)
    }

    /// The deliberate double scan: two takes of one unit from the box, on two tablets apart. One dispute, both
    /// branches.
    func testDoubleScanIsOneDisputeWithBothBranches() throws {
        let pack = store.pull(.checkOut, "JKT-RAIN-M-BLU#001", from: Custodian.store, to: "box-07", device: "tablet-b")
        try store.checkOut(unit: "JKT-RAIN-M-BLU#001", from: "box-07", to: "tablet-a", actingFor: nil)
        XCTAssertTrue(model.disputes.isEmpty)
        store.pull(.checkOut, "JKT-RAIN-M-BLU#001", from: "box-07", to: "tablet-b", device: "tablet-b", prev: pack.id)

        XCTAssertEqual(model.disputes.count, 1)
        let dispute = try XCTUnwrap(model.disputes.first)
        XCTAssertEqual(dispute.kind, .doubleScan)
        XCTAssertTrue(dispute.isFork)
        XCTAssertEqual(dispute.disputeKey, "JKT-RAIN-M-BLU#001|\(pack.id)")
        XCTAssertEqual(dispute.sides.map(\.device), ["tablet-a", "tablet-b"], "side by side, oldest first")
        XCTAssertEqual(dispute.sides.map(\.role), [.branch, .branch])
        XCTAssertEqual(dispute.sides.map(\.to), ["tablet-a", "tablet-b"])
        XCTAssertNil(dispute.note)
    }

    /// Rule 8: tablet-a sells a unit tablet-b holds. The movement and its predecessor, and who did not hold it.
    func testForeignMovementShowsTheMovementAndItsPredecessor() throws {
        let pack = store.pull(.checkOut, "JKT-RAIN-M-BLU#002", from: Custodian.store, to: "box-07", device: "tablet-b")
        let take = store.pull(.checkOut, "JKT-RAIN-M-BLU#002", from: "box-07", to: "tablet-b", device: "tablet-b",
                              prev: pack.id)
        let sale = try store.sell(unit: "JKT-RAIN-M-BLU#002", tender: Tender(kind: .cash, amount: Money(cents: 12900)),
                                  price: Money(cents: 12900), basket: UUID().uuidString.lowercased())

        let dispute = try XCTUnwrap(model.disputes.first)
        XCTAssertEqual(model.disputes.count, 1)
        XCTAssertEqual(dispute.kind, .foreignMovement)
        XCTAssertFalse(dispute.isFork)
        XCTAssertEqual(dispute.sides.map(\.id), [take.id, sale.id])
        XCTAssertEqual(dispute.sides.map(\.role), [.before, .flagged])
        XCTAssertEqual(dispute.note, "tablet-a did not hold it")
    }

    /// Decision 009: a fork at a flagged movement shares its dispute key; they are two disputes, not one.
    func testForkAtAFlaggedMovementIsItsOwnDispute() throws {
        let checkIn = try store.checkIn(unit: "JKT-RAIN-M-BLU#003")  // no record: unexpected check-in
        try store.checkOut(unit: "JKT-RAIN-M-BLU#003", from: "box-07", to: "tablet-a", actingFor: nil)
        store.pull(.checkOut, "JKT-RAIN-M-BLU#003", from: "box-07", to: "tablet-b", device: "tablet-b", prev: checkIn.id)

        XCTAssertEqual(model.disputes.map(\.disputeKey), ["JKT-RAIN-M-BLU#003|\(checkIn.id)",
                                                          "JKT-RAIN-M-BLU#003|\(checkIn.id)"])
        XCTAssertEqual(model.disputes.map(\.isFork), [true, false])
        XCTAssertEqual(model.disputes.map(\.kind), [.doubleScan, .unexpectedCheckIn])
        XCTAssertEqual(model.disputes.last?.sides.map(\.role), [.flagged])
        XCTAssertEqual(model.disputes.last?.note, "tablet-a did not hold it (no earlier record of the unit)")
    }

    /// Open only: HQ's resolution closes the dispute on the tablet as soon as it arrives.
    func testAResolvedDisputeLeaves() throws {
        let checkIn = try store.checkIn(unit: "JKT-RAIN-M-BLU#004")
        XCTAssertEqual(model.disputes.count, 1)
        let open = try XCTUnwrap(Ledger.exceptions(for: store.currentState, detector: "hq", trip: TestData.trip,
                                                   box: nil).first)
        XCTAssertEqual(open.transactions, [checkIn.id])

        var body = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(open)) as? [String: Any])
        body["status"] = "resolved"
        body["resolution"] = ["by": "hq", "at": "2026-10-18T15:00:00Z", "hlc": "1792335600000-0000-hq",
                              "chosen_txn": NSNull(), "note": "Found on the table."]
        store.pull(resolution: try JSONDecoder().decode(ExceptionDoc.self,
                                                        from: JSONSerialization.data(withJSONObject: body)))
        XCTAssertTrue(model.disputes.isEmpty)
    }
}
