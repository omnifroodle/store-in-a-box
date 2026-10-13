import XCTest
@testable import SIABCore

/// The Swift half of the differential test (decision 010; `scripts/ledger_diff.py`, `scripts/ledger_diff.sh`): with
/// `SIAB_DIFF_SETS` set to a directory of differential sets, runs every `*.json` set as the fixture runner does
/// (`LedgerFixtureTests.result`: rule 0, reduce, exceptions, conservation, drops) and writes the report to
/// `SIAB_DIFF_OUT`: one JSON object keyed by file name, canonical (sorted keys, no spaces, ASCII), byte-compatible
/// with `python -m siab_ledger report`. Skipped when `SIAB_DIFF_SETS` is not set. On a simulator, pass the variables
/// to `xcodebuild` with the `TEST_RUNNER_` prefix.
final class LedgerDifferentialTests: XCTestCase {
    /// A differential set: a ledger fixture without `expected`, with its detector, whose documents may be invalid.
    struct DiffSet: Decodable {
        var name: String
        var trip: String
        var box: String
        var store: String
        var detector: String
        var inventory: [Inventory]?
        var transactions: [JSONValue]
        var resolutions: [JSONValue]
    }

    static func report(sets directory: URL) throws -> String {
        let files = try FileManager.default.contentsOfDirectory(atPath: directory.path)
            .filter { $0.hasSuffix(".json") }
            .sorted { $0.unicodeScalars.lexicographicallyPrecedes($1.unicodeScalars) }
        var results: [String: JSONValue] = [:]
        for file in files {
            let set = try JSONDecoder().decode(DiffSet.self, from: Data(contentsOf: directory.appendingPathComponent(file)))
            results[file] = LedgerFixtureTests.result(trip: set.trip, box: set.box, store: set.store,
                                                      detector: set.detector, inventory: set.inventory,
                                                      transactions: set.transactions, resolutions: set.resolutions)
        }
        return JSONValue.object(results).canonical
    }

    func testReportForTheDifferentialSets() throws {
        let env = ProcessInfo.processInfo.environment
        guard let sets = env["SIAB_DIFF_SETS"], !sets.isEmpty else {
            throw XCTSkip("SIAB_DIFF_SETS is not set (scripts/ledger_diff.sh sets it)")
        }
        guard let out = env["SIAB_DIFF_OUT"], !out.isEmpty else { return XCTFail("SIAB_DIFF_OUT is not set") }
        let report = try Self.report(sets: URL(fileURLWithPath: sets))
        XCTAssertNotEqual(report, "{}", "no sets in \(sets)")
        try Data(report.utf8).write(to: URL(fileURLWithPath: out))
        print("LedgerDifferentialTests: wrote \(out)")
    }

    /// The report's shape, without Python: one set made from a fixture gives the fixture's `expected` plus `drops`,
    /// serialised canonically.
    func testReportOfAFixtureIsItsExpected() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let source = try DocumentCheckTests.read(
            LedgerFixtureTests.fixturesDirectory().appendingPathComponent("drop-resolution-missing-field.json"))
        var set = DocumentCheckTests.object(source)
        let expected = set["expected"]!
        guard case .object(let e) = expected, case .object(let x)? = e["exceptions"] else { return XCTFail() }
        set["detector"] = x["detector"]
        for key in ["expected", "description", "order_independent"] { set[key] = nil }
        try Data(JSONValue.object(set).canonical.utf8).write(to: dir.appendingPathComponent("drop-resolution-missing-field-0.json"))

        let report = try Self.report(sets: dir)
        XCTAssertEqual(report, JSONValue.object(["drop-resolution-missing-field-0.json": expected]).canonical)
        XCTAssertTrue(report.contains(#""drops":[{"code":"missing_field","collection":"exception","id":"exc::hq::"#))
    }
}
