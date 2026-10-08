import XCTest
@testable import SIABCore

/// Every golden fixture in contracts/fixtures/ledger/, read through the test bundle's folder reference to that
/// directory (Fixtures/ledger is a symlink to it, copied into the bundle at build time; nothing is duplicated in the
/// repository). Prints one `PASS <name>` / `FAIL <name>: <difference>` line per fixture in file-name order, the same
/// report as `python -m siab_ledger check`.
final class LedgerFixtureTests: XCTestCase {
    struct Fixture: Decodable {
        var name: String
        var orderIndependent: Bool
        var trip: String
        var box: String
        var store: String
        var inventory: [Inventory]?
        var transactions: [Transaction]
        var resolutions: [ExceptionDoc]
        var expected: JSONValue
        enum CodingKeys: String, CodingKey {
            case name, orderIndependent = "order_independent", trip, box, store, inventory, transactions,
                 resolutions, expected
        }
    }

    static let shuffles = 8

    static func fixturesDirectory() throws -> URL {
        if let url = Bundle.module.url(forResource: "ledger", withExtension: nil) { return url }
        throw XCTSkip("Fixtures/ledger is missing from the test bundle")
    }

    static func loadFixtures() throws -> [(file: String, fixture: Fixture)] {
        let dir = try fixturesDirectory()
        let files = try FileManager.default.contentsOfDirectory(atPath: dir.path)
            .filter { $0.hasSuffix(".json") }
            .sorted { $0.unicodeScalars.lexicographicallyPrecedes($1.unicodeScalars) }
        return try files.map { file in
            let data = try Data(contentsOf: dir.appendingPathComponent(file))
            return (file, try JSONDecoder().decode(Fixture.self, from: data))
        }
    }

    func testEveryFixturePasses() throws {
        let fixtures = try Self.loadFixtures()
        XCTAssertGreaterThanOrEqual(fixtures.count, 33, "contracts 0.5.0 has 33 ledger fixtures")
        var lines: [String] = []
        for (file, fixture) in fixtures {
            XCTAssertEqual(file, fixture.name + ".json")
            let diff = Self.check(fixture, seed: 0)
            lines.append(diff == nil ? "PASS \(fixture.name)" : "FAIL \(fixture.name): \(diff!)")
            XCTAssertNil(diff, "\(fixture.name): \(diff ?? "")")
        }
        print("LedgerFixtureTests report:\n" + lines.joined(separator: "\n"))
    }

    // MARK: - The runner (mirrors src/siab_ledger/fixtures.py)

    static func check(_ fixture: Fixture, seed: Int) -> String? {
        if let diff = firstDifference(fixture.expected, run(fixture, fixture.transactions, fixture.resolutions)) {
            return diff
        }
        guard fixture.orderIndependent else { return nil }
        for (label, txns, res) in orderings(fixture, seed: seed) {
            if let diff = firstDifference(fixture.expected, run(fixture, txns, res)) { return "\(label): \(diff)" }
        }
        return nil
    }

    static func run(_ f: Fixture, _ txns: [Transaction], _ res: [ExceptionDoc]) -> JSONValue {
        let state = Ledger.reduce(transactions: txns, resolutions: res, store: f.store)
        let detector: String
        if case .object(let e) = f.expected, case .object(let x)? = e["exceptions"], case .string(let d)? = x["detector"] {
            detector = d
        } else {
            detector = f.box
        }
        let docs = Ledger.exceptions(for: state, detector: detector, trip: f.trip, box: f.box)
        let withInventory = f.inventory.map { inv in
            JSONValue.array(Ledger.conservation(state: state, store: f.store, inventory: inv).map(\.json))
        } ?? .null
        var out = state.json
        out["exceptions"] = .object(["detector": .string(detector),
                                     "docs": .array(docs.map { try! JSONValue(encoding: $0) })])
        out["conservation"] = .object([
            "with_inventory": withInventory,
            "venue_only": .array(Ledger.conservation(state: state, store: f.store, inventory: nil).map(\.json)),
        ])
        return .object(out)
    }

    static func orderings(_ f: Fixture, seed: Int) -> [(String, [Transaction], [ExceptionDoc])] {
        var out: [(String, [Transaction], [ExceptionDoc])] = [("reversed", f.transactions.reversed(), f.resolutions.reversed())]
        for i in 0..<shuffles {
            var rng = SplitMix64(seed: "\(seed)/\(f.name)/\(i)")
            var t = f.transactions, r = f.resolutions
            if i % 2 == 1 {  // every other run also delivers some documents twice
                t += Array(f.transactions.shuffled(using: &rng).prefix(max(1, f.transactions.count / 3)))
                r += r.prefix(1)
            }
            t.shuffle(using: &rng)
            r.shuffle(using: &rng)
            out.append(("shuffle \(i) (seed \(seed))", t, r))
        }
        return out
    }

    /// One line describing the first place `actual` differs from `expected`, or nil.
    static func firstDifference(_ expected: JSONValue, _ actual: JSONValue, _ path: String = "expected") -> String? {
        switch (expected, actual) {
        case (.object(let e), .object(let a)):
            for key in e.keys.sorted() where a[key] == nil { return "\(path).\(key): missing" }
            for key in a.keys.sorted() where e[key] == nil { return "\(path).\(key): unexpected \(a[key]!.canonical)" }
            for key in e.keys.sorted() {
                if let diff = firstDifference(e[key]!, a[key]!, "\(path).\(key)") { return diff }
            }
            return nil
        case (.array(let e), .array(let a)):
            for (i, (x, y)) in zip(e, a).enumerated() {
                if let diff = firstDifference(x, y, "\(path)[\(i)]") { return diff }
            }
            return e.count == a.count ? nil : "\(path): \(a.count) items, expected \(e.count)"
        default:
            return expected == actual ? nil : "\(path): got \(actual.canonical), expected \(expected.canonical)"
        }
    }
}

/// A small seeded generator so the shuffled re-runs are reproducible (the orders differ from Python's, which is
/// the point: any order must give the same answer).
struct SplitMix64: RandomNumberGenerator {
    var state: UInt64
    init(seed: String) {
        state = 0xcbf2_9ce4_8422_2325
        for byte in seed.utf8 { state = (state ^ UInt64(byte)) &* 0x100_0000_01b3 }
    }
    mutating func next() -> UInt64 {
        state &+= 0x9e37_79b9_7f4a_7c15
        var z = state
        z = (z ^ (z >> 30)) &* 0xbf58_476d_1ce4_e5b9
        z = (z ^ (z >> 27)) &* 0x94d0_49bb_1331_11eb
        return z ^ (z >> 31)
    }
}

func json(_ s: String?) -> JSONValue { s.map(JSONValue.string) ?? .null }
func json(_ i: Int?) -> JSONValue { i.map { .int(Int64($0)) } ?? .null }

extension LedgerState {
    /// `units`, `counts`, `allocation_counts` and `forks` in the fixtures' shape (LedgerState.to_json()).
    var json: [String: JSONValue] {
        [
            "units": .object(units.mapValues { u in
                .object(["sku": .string(u.sku), "holder": SIABCoreTests.json(u.holder),
                         "allocation": SIABCoreTests.json(u.allocation), "state": .string(u.state.rawValue),
                         "last_txn": SIABCoreTests.json(u.lastTxn)])
            }),
            "counts": .array(counts.filter { $0.value >= 1 }.sorted { $0.key < $1.key }.map { key, qty in
                .object(["custodian": .string(key.custodian), "sku": .string(key.sku), "qty": .int(Int64(qty))])
            }),
            "allocation_counts": .object(allocationCounts.mapValues { .int(Int64($0)) }),
            "forks": .array(forks.map { f in
                .object(["unit_id": .string(f.unitID), "sku": .string(f.sku), "prev_txn": SIABCoreTests.json(f.prevTxn),
                         "branches": .array(f.branches.map(JSONValue.string)), "resolved_by": SIABCoreTests.json(f.resolvedBy)])
            }),
        ]
    }
}

extension ConservationRow {
    var json: JSONValue {
        .object([
            "sku": .string(sku), "opening_on_hand": SIABCoreTests.json(openingOnHand),
            "received": SIABCoreTests.json(received), "left_store": .int(Int64(leftStore)),
            "untraced": .int(Int64(untraced)), "returned_to_store": .int(Int64(returnedToStore)),
            "store_on_hand": SIABCoreTests.json(storeOnHand),
            "in_custody": .object(inCustody.mapValues { .int(Int64($0)) }),
            "sold": .int(Int64(sold)), "disputed": .int(Int64(disputed)), "holds": .bool(holds),
        ])
    }
}
