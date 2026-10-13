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

    /// The gate's sets on #189 (finding 3), built from the fixtures as the gate built them. The expected drops are
    /// what `python -m siab_ledger report` gives for the same sets (run when they were added); the rest of each
    /// report must be the fixture's own `expected`, since every added document is dropped (or, for the `_`-key,
    /// ignored).
    func testUnicodeSetsAgreeWithThePythonReport() throws {
        func fixture(_ name: String) throws -> [String: JSONValue] {
            DocumentCheckTests.object(try DocumentCheckTests.read(
                LedgerFixtureTests.fixturesDirectory().appendingPathComponent("\(name).json")))
        }
        func array(_ v: JSONValue?) -> [JSONValue] { if case .array(let a)? = v { return a }; return [] }
        func with(_ doc: JSONValue, _ changes: [String: JSONValue]) -> JSONValue {
            .object(DocumentCheckTests.object(doc).merging(changes) { $1 })
        }
        func report(_ fx: [String: JSONValue], transactions: [JSONValue], resolutions: [JSONValue]) -> [String: JSONValue] {
            guard case .object(let expected)? = fx["expected"], case .object(let x)? = expected["exceptions"],
                  case .string(let detector)? = x["detector"], case .string(let trip)? = fx["trip"],
                  case .string(let box)? = fx["box"], case .string(let store)? = fx["store"] else { fatalError() }
            let inventory = try! JSONDecoder().decode([Inventory]?.self, from: JSONEncoder().encode(fx["inventory"]!))
            return DocumentCheckTests.object(LedgerFixtureTests.result(
                trip: trip, box: box, store: store, detector: detector, inventory: inventory,
                transactions: transactions, resolutions: resolutions))
        }
        func drops(_ list: [(String, String, String)]) -> JSONValue {
            .array(list.map { .object(["id": .string($0.0), "collection": .string($0.1), "code": .string($0.2)]) })
        }
        let transfer: [String: JSONValue] = ["kind": .string("transfer")]

        let packAndSell = try fixture("pack-and-sell")
        let txns = array(packAndSell["transactions"])
        var expected = DocumentCheckTests.object(packAndSell["expected"]!)
        let cases: [(String, [JSONValue], JSONValue)] = [
            ("adv-u-canon-pair", [with(txns[0], ["_id": .string("txn::\u{e9}")].merging(transfer) { $1 }),
                                  with(txns[0], ["_id": .string("txn::e\u{301}")])],
             drops([("txn::e\u{301}", "transaction", "rule"), ("txn::\u{e9}", "transaction", "invalid_value")])),
            ("adv-u-hangul", [with(txns[0], ["_id": .string("txn::\u{d55c}")].merging(transfer) { $1 }),
                              with(txns[0], ["_id": .string("txn::\u{1112}\u{1161}\u{11ab}")])],
             drops([("txn::\u{1112}\u{1161}\u{11ab}", "transaction", "rule"),
                    ("txn::\u{d55c}", "transaction", "invalid_value")])),
            ("adv-u-angstrom", [with(txns[0], ["_id": .string("txn::\u{212b}")].merging(transfer) { $1 }),
                                with(txns[0], ["_id": .string("txn::\u{c5}")]),
                                with(txns[0], ["_id": .string("txn::A\u{30a}")].merging(transfer) { $1 })],
             drops([("txn::A\u{30a}", "transaction", "invalid_value"), ("txn::\u{c5}", "transaction", "rule"),
                    ("txn::\u{212b}", "transaction", "invalid_value")])),
        ]
        for (name, added, want) in cases {
            let got = report(packAndSell, transactions: txns + added, resolutions: [])
            XCTAssertEqual(got["drops"], want, name)
            expected["drops"] = want
            XCTAssertNil(LedgerFixtureTests.firstDifference(.object(expected), .object(got)), name)
        }

        // adv-f-underscore-comb: the sale carries a key `_` + U+0301 + `x`; Python ignores it, so must Swift.
        var marked = txns
        marked[3] = with(txns[3], ["_\u{301}x": .int(1)])
        let underscore = report(packAndSell, transactions: marked, resolutions: [])
        XCTAssertNil(LedgerFixtureTests.firstDifference(packAndSell["expected"]!, .object(underscore)), "adv-f-underscore-comb")

        // adv-ur-canon-pair: resolved-fork's resolution under two ids that differ only by normalisation.
        let resolvedFork = try fixture("resolved-fork")
        let resolution = array(resolvedFork["resolutions"])[0]
        let ur = report(resolvedFork, transactions: array(resolvedFork["transactions"]),
                        resolutions: [with(resolution, ["_id": .string("exc::\u{e9}")]),
                                      with(resolution, ["_id": .string("exc::e\u{301}")])])
        XCTAssertEqual(ur["drops"], drops([("exc::e\u{301}", "exception", "rule"), ("exc::\u{e9}", "exception", "rule")]),
                       "adv-ur-canon-pair")
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
