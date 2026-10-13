import XCTest
@testable import SIABCore

/// Rule 0 in Swift: the same code as the Python reference (`src/siab_ledger/ingest.py`) for every document.
final class DocumentCheckTests: XCTestCase {
    /// The code the reference gives each invalid document of `contracts/fixtures/docs/`: a copy of `INVALID_CODES` in
    /// `tests/ledger/test_ingest.py`.
    static let invalidCodes: [String: DropCode] = [
        "allocation/closed-without-closed-at": .invalidValue,
        "allocation/qty": .extraField,
        "exception/oversell-one-transaction": .invalidValue,
        "exception/resolved-without-hlc": .missingField,
        "exception/resolved-without-resolution": .invalidValue,
        "inventory/negative-opening": .invalidValue,
        "inventory/stored-on-hand": .extraField,
        "product/decimal-price": .missingField,
        "product/margin": .extraField,
        "product/no-regions": .invalidValue,
        "transaction/check-out-to-customer": .invalidValue,
        "transaction/sale-without-tender": .invalidValue,
        "transaction/sku-not-unit-sku": .rule,
        "trip/state-name": .invalidValue,
        "trip/status-open": .invalidValue,
    ]

    /// The repository's `contracts/`, found from this file (the simulator reads the host's file system).
    static var contracts: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("contracts")
    }

    static func read(_ url: URL) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Data(contentsOf: url))
    }

    static func object(_ value: JSONValue) -> [String: JSONValue] {
        guard case .object(let o) = value else { fatalError("not an object") }
        return o
    }

    /// The pack of double-scan.json, a valid transaction.
    static func pack() throws -> [String: JSONValue] {
        let fixture = try read(LedgerFixtureTests.fixturesDirectory().appendingPathComponent("double-scan.json"))
        guard case .array(let txns)? = object(fixture)["transactions"] else { fatalError("no transactions") }
        return object(txns[0])
    }

    /// The double-scan exception of double-scan.json, as a detector writes it (with `detected_at`), resolved by HQ.
    static func resolved() throws -> [String: JSONValue] {
        let fixture = try read(LedgerFixtureTests.fixturesDirectory().appendingPathComponent("double-scan.json"))
        guard case .object(let expected)? = object(fixture)["expected"], case .object(let exceptions)? = expected["exceptions"],
              case .array(let docs)? = exceptions["docs"] else { fatalError("no exception") }
        var exc = object(docs[0])
        exc["detected_at"] = .string("1792328600000-0000-tablet-a")
        exc["status"] = .string("resolved")
        exc["resolution"] = .object(["by": .string("hq"), "at": .string("2026-10-18T13:20:00Z"),
                                     "hlc": .string("1792329600000-0000-hq"),
                                     "chosen_txn": .string("txn::1792328510000-0000-tablet-a"), "note": .string("")])
        return exc
    }

    /// The code for `body` under its own `_id`.
    func code(_ body: [String: JSONValue], _ collection: String = "transaction") -> DropCode? {
        guard case .string(let id)? = body["_id"] else { fatalError("no _id") }
        return DocumentCheck.check(body, id: id, collection: collection)?.code
    }

    // MARK: - The corpus

    func testDocsCorpus() throws {
        let docs = Self.contracts.appendingPathComponent("fixtures/docs")
        var invalid: Set<String> = []
        var checked = 0
        for collection in try FileManager.default.contentsOfDirectory(atPath: docs.path).sorted() where !collection.hasPrefix(".") {
            for kind in ["valid", "invalid"] {
                let dir = docs.appendingPathComponent(collection).appendingPathComponent(kind)
                for file in try FileManager.default.contentsOfDirectory(atPath: dir.path).sorted() where file.hasSuffix(".json") {
                    let name = "\(collection)/\(file.dropLast(5))"
                    let body = Self.object(try Self.read(dir.appendingPathComponent(file)))
                    guard case .string(let id)? = body["_id"] else { return XCTFail("\(name) has no _id") }
                    let drop = DocumentCheck.check(body, id: id, collection: collection)
                    if kind == "valid" {
                        XCTAssertNil(drop, "\(name): \(drop?.detail ?? "")")
                    } else {
                        invalid.insert(name)
                        XCTAssertEqual(drop?.code, Self.invalidCodes[name], "\(name): \(drop?.detail ?? "accepted")")
                        XCTAssertEqual(drop?.id, id)
                        XCTAssertEqual(drop?.collection, collection)
                        XCTAssertFalse(drop?.detail.isEmpty ?? true)
                    }
                    checked += 1
                }
            }
        }
        XCTAssertEqual(invalid, Set(Self.invalidCodes.keys), "the corpus and the list of codes differ")
        XCTAssertGreaterThanOrEqual(checked, 30)
    }

    /// Each Swift schema is the contract file's, keyword for keyword (annotations aside): a schema change fails here
    /// until `StoreSchema` mirrors it.
    func testSchemasMirrorTheContracts() throws {
        func strip(_ value: JSONValue) -> JSONValue {
            let annotations: Set<String> = ["$schema", "$id", "title", "description", "x-id-template", "$defs", "$comment"]
            switch value {
            case .object(let o):
                return .object(o.filter { !annotations.contains($0.key) }.mapValues(strip))
            case .array(let a): return .array(a.map(strip))
            default: return value
            }
        }
        let store = Self.contracts.appendingPathComponent("schemas/store")
        let files = try FileManager.default.contentsOfDirectory(atPath: store.path).filter { $0.hasSuffix(".schema.json") }
        XCTAssertEqual(Set(files.map { String($0.dropLast(".schema.json".count)) }), Set(StoreSchema.collections.keys))
        for file in files {
            let name = String(file.dropLast(".schema.json".count))
            let raw = try Self.read(store.appendingPathComponent(file))
            let mine = StoreSchema.collections[name]!.json
            XCTAssertNil(LedgerFixtureTests.firstDifference(strip(raw), mine, name), name)
            XCTAssertEqual(Self.object(raw)["x-id-template"], .string(StoreSchema.idTemplates[name]!), name)
        }
        let common = Self.object(try Self.read(Self.contracts.appendingPathComponent("schemas/common.schema.json")))
        XCTAssertNil(LedgerFixtureTests.firstDifference(strip(common["$defs"]!), StoreSchema.commonDefs, "$defs"))
    }

    // MARK: - The derivation

    func testCodePriorityAndOneDropPerID() throws {
        let pack = try Self.pack()
        let id = "txn::1792328410000-0000-tablet-a"
        var missingAndExtra = pack
        missingAndExtra["device_clock"] = nil
        missingAndExtra["note"] = .string("edited")
        XCTAssertEqual(code(missingAndExtra), .missingField)

        var extra = pack
        extra["note"] = .string("edited")
        var badKind = pack
        badKind["kind"] = .string("transfer")
        for bodies in [[extra, badKind], [badKind, extra], [badKind, extra, badKind]] {
            let result = DocumentCheck.ingest(bodies.map { (id, $0) }, collection: "transaction", as: Transaction.self)
            XCTAssertEqual(result.accepted, [])
            XCTAssertEqual(result.drops.map { [$0.id, $0.code.rawValue] }, [[id, "extra_field"]])
        }

        // A valid body under the same id is reduced; the drop still names the id.
        let result = DocumentCheck.ingest([badKind, pack, extra].map { (id, $0) }, collection: "transaction",
                                          as: Transaction.self)
        XCTAssertEqual(result.accepted.map(\.id), [id])
        XCTAssertEqual(result.drops.map { [$0.id, $0.code.rawValue] }, [[id, "extra_field"]])

        // Keys beginning with _ are fixture metadata.
        var marked = pack
        marked["_why"] = .string("x"); marked["_invalid"] = .string("y"); marked["_anything"] = .int(1)
        XCTAssertNil(code(marked))

        // The order of the checks: wrong_type, version, then the schema, then the rules.
        var c = pack; c["type"] = .string("exception"); c["v"] = .int(2)
        XCTAssertEqual(code(c), .wrongType)
        c = pack; c["type"] = nil
        XCTAssertEqual(code(c), .wrongType)
        c = pack; c["v"] = .int(2); c["kind"] = .string("transfer")
        XCTAssertEqual(code(c), .version)
        c = pack; c["v"] = nil
        XCTAssertEqual(code(c), .version)
        c = pack; c["v"] = .bool(true)
        XCTAssertEqual(code(c), .version)
        c = pack; c["v"] = .double(1)
        XCTAssertNil(code(c), "1.0 is 1, as in Python")
        c = pack; c["kind"] = .string("transfer"); c["sku"] = .string("JKT-RAIN-L-BLU")
        XCTAssertEqual(code(c), .invalidValue)
        c = pack; c["sku"] = .string("JKT-RAIN-L-BLU")
        XCTAssertEqual(code(c), .rule)
    }

    func testDropsAreSortedAndCarryWords() throws {
        let pack = try Self.pack()
        var a = pack; a["kind"] = .string("transfer")
        var b = pack; b["v"] = .int(2)
        let result = DocumentCheck.ingest([("txn::b", a), ("txn::a", b)], collection: "transaction", as: Transaction.self)
        XCTAssertEqual(result.drops, [Drop(id: "txn::a", collection: "transaction", code: .version, detail: "v: 2, not 1"),
                                      Drop(id: "txn::b", collection: "transaction", code: .invalidValue,
                                           detail: result.drops[1].detail)])
        XCTAssertTrue(result.drops[1].detail.contains("transfer"), result.drops[1].detail)
        XCTAssertEqual(DropCode.allCases.map(\.words), ["malformed", "wrong type", "newer schema: update the app",
                                                         "missing field", "unknown field", "invalid value", "rule"])
    }

    /// `anyOf` [object, null] takes the code of the alternative the value is meant for (#177): an object missing a
    /// key is `missing_field`, a value of another JSON type `invalid_value`.
    func testAnyOfTakesTheSmallestCodeOfItsAlternatives() throws {
        var exc = try Self.resolved()
        XCTAssertNil(code(exc, "exception"), "the crafted resolution is valid")
        guard case .object(var resolution)? = exc["resolution"] else { return XCTFail() }
        resolution["note"] = nil
        exc["resolution"] = .object(resolution)
        XCTAssertEqual(code(exc, "exception"), .missingField)
        resolution["note"] = .string(""); resolution["chosen_txn"] = .int(5)
        exc["resolution"] = .object(resolution)
        XCTAssertEqual(code(exc, "exception"), .invalidValue)
        resolution["chosen_txn"] = .null; resolution["extra"] = .bool(true)
        exc["resolution"] = .object(resolution)
        XCTAssertEqual(code(exc, "exception"), .extraField)

        let sale = Self.object(try Self.read(Self.contracts.appendingPathComponent("fixtures/docs/transaction/valid/sale.json")))
        XCTAssertNil(code(sale))
        var c = sale; c["tender"] = .object(["kind": .string("cash")])
        XCTAssertEqual(code(c), .missingField)
        c = sale; c["price"] = .string("129.00")
        XCTAssertEqual(code(c), .invalidValue)
        c = sale; c["price"] = .object(["cents": .double(12.5), "currency": .string("USD")])
        XCTAssertEqual(code(c), .invalidValue)
        c = sale; c["price"] = .object(["cents": .double(12900), "currency": .string("USD")])
        XCTAssertNil(code(c), "an integral float is an integer, as in jsonschema")
        c = sale; c["price"] = .object(["cents": .int(-1), "currency": .string("USD")])
        XCTAssertEqual(code(c), .invalidValue)
        c = sale; c["price"] = .object(["cents": .bool(true), "currency": .string("USD")])
        XCTAssertEqual(code(c), .invalidValue)
        c = sale; c["price"] = .null
        XCTAssertEqual(code(c), .invalidValue, "a sale carries a price (the conditional)")
    }

    func testConditionalsAndNestedValues() throws {
        let pack = try Self.pack()
        var c = pack; c["to_custodian"] = .string("customer")
        XCTAssertEqual(code(c), .invalidValue, "nothing but a sale goes to the customer")
        c = pack; c["to_custodian"] = .string("unknown")
        XCTAssertEqual(code(c), .invalidValue)
        c = pack; c["box"] = .null
        XCTAssertEqual(code(c), .invalidValue, "box is null only when hq wrote it")
        c["device"] = .string("hq"); c["hlc"] = .string("1792328410000-0000-hq"); c["_id"] = .string("txn::1792328410000-0000-hq")
        XCTAssertNil(code(c))
        c = pack; c["from_custodian"] = .string("unknown")
        XCTAssertEqual(code(c), .invalidValue, "unknown is a source only for a check-in")
        c = pack; c["prev_txn"] = .string("txn::bad")
        XCTAssertEqual(code(c), .invalidValue)
        c = pack; c["device_clock"] = .string("2026-10-18T13:00:10")
        XCTAssertEqual(code(c), .invalidValue)

        var exc = try Self.resolved()
        guard case .array(var branches)? = exc["branches"], case .object(var branch) = branches[0] else { return XCTFail() }
        branch["hlc"] = nil
        branches[0] = .object(branch)
        exc["branches"] = .array(branches)
        XCTAssertEqual(code(exc, "exception"), .missingField, "a missing key at any depth")
        exc = try Self.resolved()
        exc["transactions"] = .array([.string("txn::1792328510000-0000-tablet-a")])
        XCTAssertEqual(code(exc, "exception"), .invalidValue, "a fork has at least two branches")
        exc = try Self.resolved()
        exc["status"] = .string("open")
        XCTAssertEqual(code(exc, "exception"), .invalidValue, "an open exception has no resolution")
    }

    func testCrossFieldRules() throws {
        let pack = try Self.pack()
        var c = pack; c["device"] = .string("tablet-b")
        XCTAssertEqual(code(c), .rule)
        var exc = try Self.resolved()
        guard case .array(let txns)? = exc["transactions"] else { return XCTFail() }
        exc["transactions"] = .array(txns.reversed())
        XCTAssertEqual(code(exc, "exception"), .rule, "transactions not sorted")
        exc = try Self.resolved()
        exc["dispute_key"] = .string("SOC-WOOL-M#001|root")
        XCTAssertEqual(code(exc, "exception"), .rule)
        exc = try Self.resolved()
        guard case .object(var resolution)? = exc["resolution"] else { return XCTFail() }
        resolution["hlc"] = .string("1792329600000-0000-tablet-a")
        exc["resolution"] = .object(resolution)
        XCTAssertEqual(code(exc, "exception"), .rule)
    }

    /// The id template is part of rule 0 (contracts 0.7.0, `drop-id-mismatch`): an id that is not what the template
    /// gives for the body is `rule`, after every schema check.
    func testIDTemplate() throws {
        let pack = try Self.pack()
        XCTAssertEqual(DocumentCheck.check(pack, id: "txn::bad", collection: "transaction")?.code, .rule)
        XCTAssertEqual(DocumentCheck.check(pack, id: "txn::1792328410000-0001-tablet-a", collection: "transaction")?.code,
                       .rule)
        var c = pack; c["kind"] = .string("transfer")
        XCTAssertEqual(DocumentCheck.check(c, id: "txn::bad", collection: "transaction")?.code, .invalidValue,
                       "a schema failure comes first")

        let exc = try Self.resolved()
        XCTAssertEqual(StoreSchema.expectedID("exception", exc), "exc::tablet-a::JKT-RAIN-M-BLU#001::111c7a4e")
        XCTAssertEqual(DocumentCheck.check(exc, id: "exc::hq::JKT-RAIN-M-BLU#001::111c7a4e", collection: "exception")?.code,
                       .rule, "the detector is part of the id")
        var other = exc
        guard case .array(let txns)? = exc["transactions"], case .array(let branches)? = exc["branches"] else {
            return XCTFail()
        }
        other["transactions"] = .array(Array(txns.prefix(1)) + [.string("txn::1792328512000-0000-tablet-b")])
        var branch = Self.object(branches[1])
        branch["txn"] = .string("txn::1792328512000-0000-tablet-b"); branch["hlc"] = .string("1792328512000-0000-tablet-b")
        other["branches"] = .array([branches[0], .object(branch)])
        XCTAssertEqual(code(other, "exception"), .rule, "the hash covers the transactions")

        let trip = Self.object(try Self.read(Self.contracts.appendingPathComponent("fixtures/docs/trip/valid/riverfest-planned.json")))
        XCTAssertNil(code(trip, "trip"))
        XCTAssertEqual(DocumentCheck.check(trip, id: "trip::other", collection: "trip")?.code, .rule)
    }

    /// `date-time` as Python's `fromisoformat` reads it, and `pattern` as `re.search` (a final newline passes `$`).
    func testFormatsAndPatternsAsPython() {
        let ok = ["2026-10-18T13:00:00Z", "2026-10-18T13:00:00.1234567+00:00", "2026-10-18T13:00:00+00:99",
                  "2026-10-18T13:00:00-23:59", "2024-02-29T00:00:00Z"]
        let bad = ["2026-10-18T24:00:00Z", "2026-10-18T13:00:60Z", "2026-10-18T13:00:00+24:00", "2026-10-18T13:00:00+23:60",
                   "2026-02-30T13:00:00Z", "0000-01-01T00:00:00Z", "2025-02-29T00:00:00Z", "2026-10-18T13:00:00.+00:00",
                   "2026-10-18 13:00:00Z", "2026-10-18T13:00:00z", "2026-10-18T13:00:00Z\n"]
        for s in ok { XCTAssertTrue(SchemaEvaluator.isFormat(s, "date-time"), s) }
        for s in bad { XCTAssertFalse(SchemaEvaluator.isFormat(s, "date-time"), s) }
        XCTAssertTrue(SchemaEvaluator.isFormat("2024-02-29", "date"))
        XCTAssertFalse(SchemaEvaluator.isFormat("2025-02-29", "date"))
        XCTAssertFalse(SchemaEvaluator.isFormat("0000-01-01", "date"))
        XCTAssertTrue(SchemaEvaluator.matches("tablet-a\n", Common.name))
        XCTAssertFalse(SchemaEvaluator.matches("tablet-a\n\n", Common.name))
        XCTAssertFalse(SchemaEvaluator.matches("Tablet-a", Common.name))
        // jsonschema's equal: by code point (Swift's == would call these two equal), 1 == 1.0, true != 1.
        XCTAssertFalse(SchemaEvaluator.equal(.string("\u{e9}"), .string("e\u{301}")))
        XCTAssertTrue(SchemaEvaluator.equal(.int(1), .double(1)))
        XCTAssertFalse(SchemaEvaluator.equal(.bool(true), .int(1)))
    }

    /// Gate finding 3 on #189: ids and keys by code point, as Python and Couchbase Lite compare them.
    func testIDsAndUnderscoreKeysByCodePoint() throws {
        let pack = try Self.pack()
        var bad = pack; bad["kind"] = .string("transfer")
        let ids = ["txn::\u{e9}", "txn::e\u{301}", "txn::\u{212b}", "txn::\u{c5}", "txn::A\u{30a}", "txn::\u{d55c}",
                   "txn::\u{1112}\u{1161}\u{11ab}"]
        let result = DocumentCheck.ingest(ids.map { ($0, bad) }, collection: "transaction", as: Transaction.self)
        XCTAssertEqual(result.drops.count, ids.count, "one drop per code-point id")
        XCTAssertEqual(result.drops.map { $0.id.unicodeScalars.map(\.value) },
                       ids.map { $0.unicodeScalars.map(\.value) }.sorted { $0.lexicographicallyPrecedes($1) })

        var marked = pack
        marked["_\u{301}x"] = .int(1)
        XCTAssertNil(code(marked), "_ followed by a combining mark is metadata, as Python's startswith")
        var field = pack
        field["\u{301}_x"] = .int(1)
        XCTAssertEqual(code(field), .extraField)
    }

    func testRawDocumentsThatCannotBeNamedAreMalformed() throws {
        let result = DocumentCheck.ingest(documents: [.string("txn"), .object(["_id": .int(5)]), .array([])],
                                          collection: "transaction", as: Transaction.self)
        XCTAssertEqual(result.accepted, [])
        XCTAssertEqual(result.drops.map { [$0.id, $0.code.rawValue] }, [["", "malformed"]])
        let named = DocumentCheck.ingest(documents: [.object(["_id": .string("x")])], collection: "transaction",
                                         as: Transaction.self)
        XCTAssertEqual(named.drops.map { [$0.id, $0.code.rawValue] }, [["x", "wrong_type"]])
    }
}
