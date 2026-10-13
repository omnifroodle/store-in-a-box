import XCTest
@testable import SIABCore

/// `Ledger.isUnitID`, the check the Diagnostics screen's movement check uses before it writes (#133 item 2).
final class UnitIDTests: XCTestCase {
    func testAUnitIDIsAWholeStringMatch() {
        for good in ["JKT-RAIN-M-BLU#001", "HAT-BEANIE-OS#999", "A#000", "TEE1-2#123"] {
            XCTAssertTrue(Ledger.isUnitID(good), good)
        }
        let bad = [
            "JKT-RAIN-M-BLU#001\n",  // what `^...$` let through: `$` also matches before a final newline
            "JKT-RAIN-M-BLU#001\r\n", "\nJKT-RAIN-M-BLU#001", " JKT-RAIN-M-BLU#001", "JKT-RAIN-M-BLU#001 ",
            "JKT-RAIN-M-BLU#001\nJKT-RAIN-M-BLU#002", "jkt-rain-m-blu#001", "JKT-RAIN-M-BLU#01", "JKT-RAIN-M-BLU#0001",
            "JKT--RAIN#001", "-JKT#001", "JKT-#001", "JKT-RAIN-M-BLU", "#001", "",
        ]
        for text in bad { XCTAssertFalse(Ledger.isUnitID(text), text.debugDescription) }
    }

    /// The old check, for the record: under ICU (`NSRegularExpression`, which backs `String.range(of:options:
    /// .regularExpression)` on the iOS 17 Foundation; a newer Foundation may not) the anchored pattern accepts the
    /// trailing newline. `isUnitID` does not depend on which engine runs.
    func testTheAnchoredRegexAcceptedATrailingNewline() throws {
        let anchored = try NSRegularExpression(pattern: "^[A-Z0-9]+(-[A-Z0-9]+)*#[0-9]{3}$")
        let text = "JKT-RAIN-M-BLU#001\n"
        XCTAssertNotNil(anchored.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)))
        XCTAssertFalse(Ledger.isUnitID(text))
    }
}
