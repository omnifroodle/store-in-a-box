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

    /// Virtual time: a label held in view is one scan; it scans again only after leaving view for the window.
    func testDebounceMakesOneLabelOneScan() {
        var debouncer = ScanDebouncer(window: 1.5)
        XCTAssertTrue(debouncer.admit("JKT-RAIN-M-BLU#001", at: 10.0))
        for t in stride(from: 10.1, through: 14.0, by: 0.1) {
            XCTAssertFalse(debouncer.admit("JKT-RAIN-M-BLU#001", at: t), "still in view at \(t)")
        }
        XCTAssertTrue(debouncer.admit("JKT-RAIN-M-BLU#002", at: 14.0), "another label is a new scan at once")
        XCTAssertTrue(debouncer.admit("JKT-RAIN-M-BLU#001", at: 15.6), "out of view for 1.6 s: a new scan")
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
