import XCTest
@testable import StoreInABox

@MainActor
final class ScannerParserTests: XCTestCase {
    func testPayloadGrammar() throws {
        let scan = try ScanParser.parse("JKT-RAIN-M-BLU#007").get()
        XCTAssertEqual(scan, ScanResult(unit: "JKT-RAIN-M-BLU#007", sku: "JKT-RAIN-M-BLU", serial: "007"))
        XCTAssertEqual(try ScanParser.parse("HAT-BEANIE-OS#120\n").get().unit, "HAT-BEANIE-OS#120",
                       "a scanner's trailing newline is not part of the label")

        for bad in ["JKT-RAIN-M-BLU", "#007", "jkt-rain-m-blu#007", "JKT-RAIN-M-blu#007", "JKT-RAIN-M-BLU#07",
                    "JKT-RAIN-M-BLU#0071", "JKT-RAIN-M-BLU#00A", "JKT--RAIN#007", "-JKT#007", "JKT-RAIN-M-BLU#007#008",
                    "JKT RAIN#007", ""] {
            guard case .failure(.malformed) = ScanParser.parse(bad) else { return XCTFail("accepted \(bad)") }
        }
    }

    func testUnknownSKUIsRefusedWithItsName() {
        let result = ScanParser.parse("PCK-DAY-20#001", knownSKU: { $0 == "JKT-RAIN-M-BLU" })
        XCTAssertEqual(result, .failure(.unknownSKU("PCK-DAY-20")))
        XCTAssertEqual(ScanRejection.unknownSKU("PCK-DAY-20").reason, "Unknown SKU PCK-DAY-20")
    }

    /// Virtual time: a label held in view is one scan, however long it stays there.
    func testDebounceMakesOneLabelOneScan() {
        var debouncer = ScanDebouncer(gone: 0.5, repeatAfter: 1.0)
        XCTAssertTrue(debouncer.admit("JKT-RAIN-M-BLU#001", at: 10.0))
        for t in stride(from: 10.1, through: 14.0, by: 0.1) {
            XCTAssertFalse(debouncer.admit("JKT-RAIN-M-BLU#001", at: t), "still in view at \(t)")
        }
        XCTAssertTrue(debouncer.admit("JKT-RAIN-M-BLU#002", at: 14.0), "another label is a new scan at once")
        XCTAssertTrue(debouncer.admit("JKT-RAIN-M-BLU#001", at: 15.6), "out of view for 1.6 s: a new scan")
    }

    /// #119 item 9: the deliberate double scan. Scanned, moved out of view, brought back: two scans, without holding it
    /// away for the old 1.5 s. A camera that loses a held label for a moment right after taking it does not take it
    /// twice.
    func testDeliberateDoubleScanIsTwoScans() {
        var debouncer = ScanDebouncer(gone: 0.5, repeatAfter: 1.0)
        XCTAssertTrue(debouncer.admit("JKT-RAIN-M-BLU#001", at: 10.0))
        XCTAssertFalse(debouncer.admit("JKT-RAIN-M-BLU#001", at: 10.3), "still in view")
        // Out of view from 10.3 to 10.9 (0.6 s), back at 1.0 s after the first scan: a second scan.
        XCTAssertTrue(debouncer.admit("JKT-RAIN-M-BLU#001", at: 11.0))
        XCTAssertFalse(debouncer.admit("JKT-RAIN-M-BLU#001", at: 11.1), "held after the second scan")

        // A dropout while held: lost for 0.6 s, 0.8 s after it was taken. Not a new scan, and still one while held.
        XCTAssertTrue(debouncer.admit("HAT-BEANIE-OS#001", at: 20.0))
        XCTAssertFalse(debouncer.admit("HAT-BEANIE-OS#001", at: 20.2))
        XCTAssertFalse(debouncer.admit("HAT-BEANIE-OS#001", at: 20.8), "back within the repeat window")
        for t in stride(from: 20.9, through: 23.0, by: 0.1) {
            XCTAssertFalse(debouncer.admit("HAT-BEANIE-OS#001", at: t), "held at \(t)")
        }
        // A short glance away (0.3 s) is not leaving view.
        XCTAssertFalse(debouncer.admit("HAT-BEANIE-OS#001", at: 23.3))
    }

    func testStationShowsTheReasonAndCallsTheScreenOnlyForAGoodLabel() {
        var now: TimeInterval = 0
        let station = ScanStation(catalog: FakeCatalog([TestData.rainShell]), feedback: SilentFeedback(),
                                  now: { now })
        var handled: [String] = []
        let handler: ScanStation.Handler = { scan in
            handled.append(scan.unit)
            return .success("Added \(scan.unit)")
        }

        station.receive("HAT-BEANIE-OS#001", handler: handler)
        XCTAssertEqual(station.notice, .rejected("Unknown SKU HAT-BEANIE-OS"))
        now = 5
        station.receive("not a label", handler: handler)
        XCTAssertEqual(station.notice, .rejected("Not a unit label: not a label"))
        now = 10
        station.receive("JKT-RAIN-M-BLU#001", handler: handler)
        XCTAssertEqual(station.notice, .accepted("Added JKT-RAIN-M-BLU#001"))
        now = 10.2
        station.receive("JKT-RAIN-M-BLU#001", handler: handler)  // the same read again: dropped
        station.receive("JKT-RAIN-M-BLU#001", debounce: false, handler: handler)  // typed: a deliberate scan
        XCTAssertEqual(handled, ["JKT-RAIN-M-BLU#001", "JKT-RAIN-M-BLU#001"])
    }
}
