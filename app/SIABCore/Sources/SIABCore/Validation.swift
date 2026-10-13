import Foundation

// Rule 0 (contracts/fixtures/README.md; decision 010; ports/ledger.md, "Ingest: how a drop's code is derived"): a node
// reduces only documents that pass their collection's schema, the cross-field rules and the id template, and records
// every drop. The
// reference is `src/siab_ledger/ingest.py`; the codes must agree with it on every document (DocumentCheckTests over
// the docs/ corpus, LedgerFixtureTests, and the differential test against the Python report).

/// Why a document was dropped, in priority order: a document's code is the first that applies.
public enum DropCode: String, Codable, CaseIterable, Comparable {
    case malformed
    case wrongType = "wrong_type"
    case version
    case missingField = "missing_field"
    case extraField = "extra_field"
    case invalidValue = "invalid_value"
    case rule

    var rank: Int { Self.allCases.firstIndex(of: self)! }
    public static func < (a: DropCode, b: DropCode) -> Bool { a.rank < b.rank }

    /// The code as both screens say it (HQ's panel, the tablet's Diagnostics): `siab_ledger.ingest.CODE_WORDS`.
    public var words: String {
        switch self {
        case .malformed: "malformed"
        case .wrongType: "wrong type"
        case .version: "newer schema: update the app"
        case .missingField: "missing field"
        case .extraField: "unknown field"
        case .invalidValue: "invalid value"
        case .rule: "rule"
        }
    }
}

/// A document rule 0 dropped. `detail` is the first failing check in words: logged and shown, never compared.
public struct Drop: Equatable, Codable {
    public var id: String
    public var collection: String
    public var code: DropCode
    public var detail: String
    public init(id: String, collection: String, code: DropCode, detail: String) {
        self.id = id; self.collection = collection; self.code = code; self.detail = detail
    }
}

public enum DocumentCheck {
    /// nil when `body` (one document; keys beginning with `_` are ignored) passes its collection's schema and the
    /// cross-field rules, and `id` is what the schema's id template gives for it; else the drop, with the first
    /// failing check's code (an id that disagrees is `rule`, fixture `drop-id-mismatch`). `collection` must be one of
    /// `StoreSchema.collections`.
    public static func check(_ body: [String: JSONValue], id: String, collection: String) -> Drop? {
        guard let schema = StoreSchema.collections[collection] else {
            preconditionFailure("no schema for collection \(collection)")
        }
        let body = body.filter { !$0.key.hasPrefix("_") }
        func drop(_ code: DropCode, _ detail: String) -> Drop { Drop(id: id, collection: collection, code: code, detail: detail) }
        if body["type"] != .string(collection) {
            return drop(.wrongType, "type: \(body["type"].map(\.canonical) ?? "required"), not \(collection)")
        }
        switch body["v"] {
        case .int(1), .double(1): break
        case let v: return drop(.version, "v: \(v.map(\.canonical) ?? "required"), not 1")
        }
        let errors = SchemaEvaluator.errors(.object(body), schema, at: [])
        if let code = errors.map(\.code).min() {
            let first = errors.filter { $0.code == code }.map { $0.leaf(code) }
                .min { ($0.where, $0.message) < ($1.where, $1.message) }!
            return drop(code, first.words)
        }
        if let rule = CrossChecks.check(collection, body).first { return drop(.rule, rule) }
        if let want = StoreSchema.expectedID(collection, body), !want.unicodeScalars.elementsEqual(id.unicodeScalars) {
            return drop(.rule, "_id \(id) should be \(want)")
        }
        return nil
    }

    /// Rule 0 over `bodies` (any order, duplicates allowed) of one collection: the bodies that pass, decoded as `T`
    /// in input order, and one drop per id, the smallest code among that id's invalid bodies (ties broken by
    /// `detail`, so the record is a function of the set), sorted by id. A valid body under an id that also has an
    /// invalid one is accepted; the drop still names the id.
    public static func ingest<T: Decodable>(_ bodies: [(id: String, body: [String: JSONValue])], collection: String,
                                            as type: T.Type) -> (accepted: [T], drops: [Drop]) {
        ingest(bodies.map { (id: $0.id, doc: JSONValue.object($0.body), named: true) }, collection: collection, as: type)
    }

    /// The same over raw documents, each a JSON object carrying its `_id`, as the fixtures and the differential sets
    /// hold them. A document that is not an object, or has no string `_id`, is `malformed` with the id `""`, as in
    /// the reference (nothing can name it).
    public static func ingest<T: Decodable>(documents: [JSONValue], collection: String,
                                            as type: T.Type) -> (accepted: [T], drops: [Drop]) {
        let items = documents.map { doc -> (id: String, doc: JSONValue, named: Bool) in
            if case .object(let body) = doc, case .string(let id)? = body["_id"] { return (id, doc, true) }
            return ("", doc, false)
        }
        return ingest(items, collection: collection, as: type)
    }

    private static func ingest<T: Decodable>(_ items: [(id: String, doc: JSONValue, named: Bool)], collection: String,
                                             as: T.Type) -> (accepted: [T], drops: [Drop]) {
        var accepted: [T] = []
        var worst: [String: Drop] = [:]
        for (id, doc, named) in items {
            var failed: Drop?
            if !named {
                failed = Drop(id: id, collection: collection, code: .malformed,
                              detail: "the document is \(SchemaEvaluator.jsonType(doc)) with no string _id")
            } else if case .object(var body) = doc {
                failed = check(body, id: id, collection: collection)
                if failed == nil {
                    body["_id"] = .string(id)
                    do {
                        accepted.append(try JSONDecoder().decode(T.self, from: JSONEncoder().encode(body)))
                    } catch {
                        // What passes the schema decodes; if it ever does not, it is dropped, never skipped.
                        failed = Drop(id: id, collection: collection, code: .malformed,
                                      detail: "the app could not read it: \(error)")
                    }
                }
            } else {
                failed = Drop(id: id, collection: collection, code: .malformed,
                              detail: "the document is \(SchemaEvaluator.jsonType(doc)), not an object")
            }
            if let drop = failed, worst[id].map({ precedes(drop, $0) }) ?? true { worst[id] = drop }
        }
        let drops = worst.values.sorted { $0.id.unicodeScalars.lexicographicallyPrecedes($1.id.unicodeScalars) }
        return (accepted, drops)
    }

    /// The smaller code first; between equal codes, the smaller detail (code point order, as Python compares).
    private static func precedes(_ a: Drop, _ b: Drop) -> Bool {
        a.code != b.code ? a.code < b.code : a.detail.unicodeScalars.lexicographicallyPrecedes(b.detail.unicodeScalars)
    }
}

// MARK: - The schemas, mirrored

/// A JSON Schema (draft 2020-12) with only the keywords `contracts/schemas/` uses. `StoreSchema` writes the six
/// collection schemas with it; `DocumentCheckTests.testSchemasMirrorTheContracts` checks that `json` equals each
/// contract file, annotations aside, so a schema change fails a test until it is mirrored here.
public struct Schema {
    var type: [String]?
    var const: JSONValue?
    var enumeration: [JSONValue]?
    var pattern: String?
    var format: String?
    var minimum: Int64?
    var minLength: Int?
    var maxLength: Int?
    var minItems: Int?
    var uniqueItems = false
    var items: [Schema] = []  // zero or one: an array so that the struct can hold itself
    var properties: [(name: String, schema: Schema)] = []
    var required: [String]?
    var additionalProperties: Bool?
    var anyOf: [Schema]?
    var allOf: [Schema]?
    var not: [Schema] = []
    var conditional: [Schema?] = []  // [if, then, else], or empty
    var ref: (name: String, target: [Schema])?

    static func types(_ names: String...) -> Schema { Schema(type: names) }
    static func ref(_ name: String) -> Schema { Schema(ref: (name, [Common.defs.first { $0.name == name }!.schema])) }
    static func nullable(_ schema: Schema) -> Schema { Schema(anyOf: [schema, .types("null")]) }
    static func constant(_ value: String) -> Schema { Schema(const: .string(value)) }
    static func oneOf(_ values: String...) -> Schema { Schema(enumeration: values.map(JSONValue.string)) }
    static func properties(_ properties: [(String, Schema)], required: [String]? = nil) -> Schema {
        Schema(properties: properties.map { ($0.0, $0.1) }, required: required)
    }
    static func object(required: [String], _ properties: [(String, Schema)], allOf: [Schema]? = nil) -> Schema {
        Schema(type: ["object"], properties: properties.map { ($0.0, $0.1) }, required: required,
               additionalProperties: false, allOf: allOf)
    }
    static func when(_ test: Schema, then: Schema? = nil, else otherwise: Schema? = nil) -> Schema {
        Schema(conditional: [test, then, otherwise])
    }
    static func not(_ schema: Schema) -> Schema { Schema(not: [schema]) }

    /// The schema as JSON, in the contract files' shape (no annotations).
    public var json: JSONValue {
        var o: [String: JSONValue] = [:]
        if let type { o["type"] = type.count == 1 ? .string(type[0]) : .array(type.map(JSONValue.string)) }
        if let const { o["const"] = const }
        if let enumeration { o["enum"] = .array(enumeration) }
        if let pattern { o["pattern"] = .string(pattern) }
        if let format { o["format"] = .string(format) }
        if let minimum { o["minimum"] = .int(minimum) }
        if let minLength { o["minLength"] = .int(Int64(minLength)) }
        if let maxLength { o["maxLength"] = .int(Int64(maxLength)) }
        if let minItems { o["minItems"] = .int(Int64(minItems)) }
        if uniqueItems { o["uniqueItems"] = .bool(true) }
        if let items = items.first { o["items"] = items.json }
        if !properties.isEmpty {
            o["properties"] = .object(Dictionary(uniqueKeysWithValues: properties.map { ($0.name, $0.schema.json) }))
        }
        if let required { o["required"] = .array(required.map(JSONValue.string)) }
        if let additionalProperties { o["additionalProperties"] = .bool(additionalProperties) }
        if let anyOf { o["anyOf"] = .array(anyOf.map(\.json)) }
        if let allOf { o["allOf"] = .array(allOf.map(\.json)) }
        if let not = not.first { o["not"] = not.json }
        if conditional.count == 3 {
            o["if"] = conditional[0]?.json
            o["then"] = conditional[1]?.json
            o["else"] = conditional[2]?.json
        }
        if let ref { o["$ref"] = .string("../common.schema.json#/$defs/\(ref.name)") }
        return .object(o)
    }
}

/// `contracts/schemas/common.schema.json`'s `$defs`.
enum Common {
    static let name = "^[a-z][a-z0-9-]*$"
    static let hlcTail = "[0-9]{13}-[0-9a-f]{4}-[a-z][a-z0-9-]*$"
    static let defs: [(name: String, schema: Schema)] = [
        ("custodian_id", Schema(type: ["string"], pattern: name)),
        ("device_id", Schema(type: ["string"], pattern: name)),
        ("sku", Schema(type: ["string"], pattern: "^[A-Z0-9]+(-[A-Z0-9]+)*$")),
        ("unit_id", Schema(type: ["string"], pattern: "^[A-Z0-9]+(-[A-Z0-9]+)*#[0-9]{3}$")),
        ("trip_id", Schema(type: ["string"], pattern: "^trip-[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+$")),
        ("region", Schema(type: ["string"], pattern: name)),
        ("hlc", Schema(type: ["string"], pattern: "^" + hlcTail)),
        ("money", .object(required: ["cents", "currency"], [
            ("cents", Schema(type: ["integer"], minimum: 0)),
            ("currency", .constant("USD")),
        ])),
        ("doc_ref_txn", Schema(type: ["string"], pattern: "^txn::" + hlcTail)),
        ("doc_ref_alloc", Schema(type: ["string"], pattern: "^alloc::" + hlcTail)),
        ("doc_ref_exc", Schema(type: ["string"],
                               pattern: "^exc::[a-z][a-z0-9-]*::[A-Z0-9]+(-[A-Z0-9]+)*#[0-9]{3}::[0-9a-f]{8}$")),
    ]
}

/// `contracts/schemas/store/*.schema.json`, one per collection.
public enum StoreSchema {
    static let movementKinds = Schema.oneOf("check_out", "check_in", "sale")
    static let dateTime = Schema(type: ["string"], format: "date-time")
    static let text80 = Schema(type: ["string"], minLength: 1, maxLength: 80)
    static let v1 = Schema(const: .int(1))

    static let transaction = Schema.object(required: [
        "v", "type", "trip", "box", "kind", "unit_id", "sku", "from_custodian", "to_custodian", "prev_txn",
        "from_allocation", "to_allocation", "device", "hlc", "device_clock", "box_clock", "basket", "price", "tender",
    ], [
        ("v", v1),
        ("type", .constant("transaction")),
        ("trip", .ref("trip_id")),
        ("box", .nullable(.ref("custodian_id"))),
        ("kind", movementKinds),
        ("unit_id", .ref("unit_id")),
        ("sku", .ref("sku")),
        ("from_custodian", .ref("custodian_id")),
        ("to_custodian", Schema(allOf: [.ref("custodian_id"), .not(.constant("unknown"))])),
        ("prev_txn", .nullable(.ref("doc_ref_txn"))),
        ("from_allocation", .nullable(.ref("doc_ref_alloc"))),
        ("to_allocation", .nullable(.ref("doc_ref_alloc"))),
        ("device", .ref("device_id")),
        ("hlc", .ref("hlc")),
        ("device_clock", dateTime),
        ("box_clock", Schema(type: ["string", "null"], format: "date-time")),
        ("basket", Schema(type: ["string", "null"],
                          pattern: "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")),
        ("price", .nullable(.ref("money"))),
        ("tender", .nullable(.object(required: ["kind", "amount"], [
            ("kind", .oneOf("cash", "card_simulated")),
            ("amount", .ref("money")),
        ]))),
    ], allOf: [
        .when(.properties([("kind", .constant("sale"))], required: ["kind"]),
              then: .properties([("to_custodian", .constant("customer")), ("to_allocation", .types("null")),
                                 ("price", .types("object")), ("tender", .types("object")),
                                 ("basket", .types("string"))]),
              else: .properties([("to_custodian", .not(.constant("customer"))), ("price", .types("null")),
                                 ("tender", .types("null")), ("basket", .types("null"))])),
        .when(.not(.properties([("device", .constant("hq"))], required: ["device"])),
              then: .properties([("box", .types("string"))])),
        .when(.properties([("from_custodian", .constant("unknown"))], required: ["from_custodian"]),
              then: .properties([("kind", .constant("check_in")), ("prev_txn", .types("null"))])),
    ])

    static let exception = Schema.object(required: [
        "v", "type", "trip", "box", "kind", "unit_id", "sku", "dispute_key", "fork_txn", "transactions", "branches",
        "proposed_resolution", "status", "resolution", "detected_by", "detected_at",
    ], [
        ("v", v1),
        ("type", .constant("exception")),
        ("trip", .ref("trip_id")),
        ("box", .nullable(.ref("custodian_id"))),
        ("kind", .oneOf("oversell", "double_scan", "unexpected_check_in", "foreign_movement")),
        ("unit_id", .ref("unit_id")),
        ("sku", .ref("sku")),
        ("dispute_key", Schema(type: ["string"], pattern:
            "^[A-Z0-9]+(-[A-Z0-9]+)*#[0-9]{3}\\|(root|txn::[0-9]{13}-[0-9a-f]{4}-[a-z][a-z0-9-]*)$")),
        ("fork_txn", .nullable(.ref("doc_ref_txn"))),
        ("transactions", Schema(type: ["array"], minItems: 1, uniqueItems: true, items: [.ref("doc_ref_txn")])),
        ("branches", Schema(type: ["array"], minItems: 1, items: [
            .object(required: ["txn", "device", "kind", "to_custodian", "hlc"], [
                ("txn", .ref("doc_ref_txn")),
                ("device", .ref("device_id")),
                ("kind", movementKinds),
                ("to_custodian", .ref("custodian_id")),
                ("hlc", .ref("hlc")),
            ]),
        ])),
        ("proposed_resolution", .object(required: ["action", "note"], [
            ("action", .oneOf("review", "refund", "backorder", "substitute")),
            ("note", .types("string")),
        ])),
        ("status", .oneOf("open", "resolved")),
        ("resolution", .nullable(.object(required: ["by", "at", "hlc", "chosen_txn", "note"], [
            ("by", .ref("device_id")),
            ("at", dateTime),
            ("hlc", .ref("hlc")),
            ("chosen_txn", .nullable(.ref("doc_ref_txn"))),
            ("note", .types("string")),
        ]))),
        ("detected_by", .ref("device_id")),
        ("detected_at", .ref("hlc")),
    ], allOf: [
        .when(.properties([("kind", .oneOf("oversell", "double_scan"))], required: ["kind"]),
              then: .properties([("transactions", Schema(minItems: 2)), ("branches", Schema(minItems: 2))])),
        .when(.properties([("status", .constant("resolved"))], required: ["status"]),
              then: .properties([("resolution", .types("object"))]),
              else: .properties([("resolution", .types("null"))])),
        .when(.properties([("detected_by", .constant("hq"))], required: ["detected_by"]),
              then: .properties([("box", .types("null"))]),
              else: .properties([("box", .types("string"))])),
    ])

    static let allocation = Schema.object(required: [
        "v", "type", "trip", "box", "sku", "custodian", "parent", "from_custodian", "opened_by", "opened_at",
        "closed_at", "status",
    ], [
        ("v", v1),
        ("type", .constant("allocation")),
        ("trip", .ref("trip_id")),
        ("box", .ref("custodian_id")),
        ("sku", .ref("sku")),
        ("custodian", .ref("custodian_id")),
        ("parent", .nullable(.ref("doc_ref_alloc"))),
        ("from_custodian", .ref("custodian_id")),
        ("opened_by", .ref("device_id")),
        ("opened_at", .ref("hlc")),
        ("closed_at", .nullable(.ref("hlc"))),
        ("status", .oneOf("active", "closed")),
    ], allOf: [
        .when(.properties([("status", .constant("closed"))], required: ["status"]),
              then: .properties([("closed_at", .types("string"))]),
              else: .properties([("closed_at", .types("null"))])),
    ])

    static let inventory = Schema.object(required: [
        "v", "type", "store", "sku", "opening_on_hand", "received", "as_of",
    ], [
        ("v", v1),
        ("type", .constant("inventory")),
        ("store", .ref("custodian_id")),
        ("sku", .ref("sku")),
        ("opening_on_hand", Schema(type: ["integer"], minimum: 0)),
        ("received", Schema(type: ["integer"], minimum: 0)),
        ("as_of", dateTime),
    ])

    static let product = Schema.object(required: [
        "v", "type", "sku", "name", "price", "category", "category_family", "size", "color", "tags", "regions",
    ], [
        ("v", v1),
        ("type", .constant("product")),
        ("sku", .ref("sku")),
        ("name", text80),
        ("price", .ref("money")),
        ("category", .oneOf("jackets", "fleece", "base-layers", "socks", "hats", "packs", "gloves")),
        ("category_family", .oneOf("outerwear", "layers", "accessories", "bags")),
        ("size", Schema(type: ["string", "null"], pattern: "^(XS|S|M|L|XL|XXL|OS|[0-9]{1,3})$")),
        ("color", Schema(type: ["string", "null"], minLength: 1, maxLength: 30)),
        ("tags", Schema(type: ["array"], uniqueItems: true, items: [Schema(type: ["string"], pattern: Common.name)])),
        ("regions", Schema(type: ["array"], minItems: 1, uniqueItems: true, items: [.ref("region")])),
    ])

    static let trip = Schema.object(required: [
        "v", "type", "trip_id", "store", "box", "region", "venue", "starts", "ends", "status", "devices",
    ], [
        ("v", v1),
        ("type", .constant("trip")),
        ("trip_id", .ref("trip_id")),
        ("store", .ref("custodian_id")),
        ("box", .ref("custodian_id")),
        ("region", .ref("region")),
        ("venue", .object(required: ["name", "city", "state"], [
            ("name", text80),
            ("city", text80),
            ("state", Schema(type: ["string"], pattern: "^[A-Z]{2}$")),
        ])),
        ("starts", Schema(type: ["string"], format: "date")),
        ("ends", Schema(type: ["string"], format: "date")),
        ("status", .oneOf("planned", "packing", "selling", "returned", "closed")),
        ("devices", Schema(type: ["array"], uniqueItems: true, items: [.ref("custodian_id")])),
    ])

    /// Every collection a node reads, by name.
    public static let collections: [String: Schema] = [
        "transaction": transaction, "exception": exception, "allocation": allocation, "inventory": inventory,
        "product": product, "trip": trip,
    ]

    /// Each schema's `x-id-template`: what a document's id must be for its body (rule 0's id check).
    public static let idTemplates: [String: String] = [
        "transaction": "txn::{hlc}", "exception": "exc::{detected_by}::{unit_id}::{sha256_8:transactions}",
        "allocation": "alloc::{opened_at}", "inventory": "inventory::{store}::{sku}", "product": "product::{sku}",
        "trip": "trip::{trip_id}",
    ]

    /// The id `collection`'s template gives for `body` (`{field}` is the field, `{sha256_8:field}` the first 8 hex
    /// characters of sha256 over its ids, sorted and joined by `|`), or nil when a field it names is missing, as
    /// `scripts/check_contracts.py`'s `expand_id`. Called on a body that passed its schema.
    static func expectedID(_ collection: String, _ body: [String: JSONValue]) -> String? {
        guard var rest = idTemplates[collection]?[...] else { return nil }
        var out = ""
        while let open = rest.firstIndex(of: "{"), let close = rest[open...].firstIndex(of: "}") {
            out += rest[..<open]
            let parts = rest[rest.index(after: open)..<close].split(separator: ":", maxSplits: 1)
            switch body[String(parts.last!)] {
            case nil: return nil
            case .string(let s)? where parts.count == 1: out += s
            case .array(let a)? where parts.count == 2 && parts[0] == "sha256_8":
                out += Ledger.hash8(a.map { if case .string(let s) = $0 { s } else { $0.canonical } })
            case let other?: out += other.canonical
            }
            rest = rest[rest.index(after: close)...]
        }
        return out + rest
    }

    /// `common.schema.json`'s `$defs`, as JSON, for the mirror test.
    public static var commonDefs: JSONValue {
        .object(Dictionary(uniqueKeysWithValues: Common.defs.map { ($0.name, $0.schema.json) }))
    }
}

// MARK: - The evaluator

/// One error, as `jsonschema`'s `iter_errors` reports it: a code from its keyword (`required` is `missing_field`,
/// `additionalProperties` is `extra_field`, any other is `invalid_value`; an `anyOf` takes the smallest code among
/// its alternatives' errors, its `context`), where it is, and words.
struct SchemaError {
    var code: DropCode
    var path: [String]
    var message: String
    var isType = false
    var context: [SchemaError] = []

    var `where`: String { path.joined(separator: ".") }

    /// The error whose words explain `code`: for an `anyOf`, the alternative's error with that code that is not a
    /// bare type mismatch, the deepest first (the alternative the value was meant for).
    func leaf(_ code: DropCode) -> SchemaError {
        guard !context.isEmpty else { return self }
        func key(_ e: SchemaError) -> (Int, Int, String, String) { (e.isType ? 1 : 0, -e.path.count, e.where, e.message) }
        return context.filter { $0.code == code }.min { key($0) < key($1) }!.leaf(code)
    }

    var words: String { "\(self.where.isEmpty ? "(root)" : self.where): \(message)" }
}

enum SchemaEvaluator {
    /// Every error `value` has against `schema`, at every depth, as `jsonschema` reports them: a keyword that does
    /// not apply to the value's JSON type (`required` on a string, `pattern` on a number) says nothing.
    static func errors(_ value: JSONValue, _ schema: Schema, at path: [String]) -> [SchemaError] {
        var out: [SchemaError] = []
        func fail(_ message: String, _ code: DropCode = .invalidValue, at place: [String]? = nil, type: Bool = false) {
            out.append(SchemaError(code: code, path: place ?? path, message: message, isType: type))
        }
        if let ref = schema.ref { out += errors(value, ref.target[0], at: path) }
        if let types = schema.type, !types.contains(where: { isType(value, $0) }) {
            fail("\(value.canonical) is not of type \(types.joined(separator: ", "))", type: true)
        }
        if let const = schema.const, !equal(value, const) { fail("\(const.canonical) was expected") }
        if let values = schema.enumeration, !values.contains(where: { equal(value, $0) }) {
            fail("\(value.canonical) is not one of \(JSONValue.array(values).canonical)")
        }
        if case .string(let s) = value {
            let length = s.unicodeScalars.count
            if let pattern = schema.pattern, !matches(s, pattern) { fail("\(value.canonical) does not match \(pattern)") }
            if let format = schema.format, !isFormat(s, format) { fail("\(value.canonical) is not a '\(format)'") }
            if let min = schema.minLength, length < min { fail("\(value.canonical) is too short") }
            if let max = schema.maxLength, length > max { fail("\(value.canonical) is too long") }
        }
        if let minimum = schema.minimum, let n = number(value), n < Double(minimum) {
            fail("\(value.canonical) is less than the minimum of \(minimum)")
        }
        if case .array(let a) = value {
            if let min = schema.minItems, a.count < min { fail("\(value.canonical) should have at least \(min) items") }
            if schema.uniqueItems, a.indices.contains(where: { i in a[..<i].contains { equal($0, a[i]) } }) {
                fail("\(value.canonical) has non-unique elements")
            }
            if let items = schema.items.first {
                for (i, element) in a.enumerated() { out += errors(element, items, at: path + [String(i)]) }
            }
        }
        if case .object(let o) = value {
            for (name, sub) in schema.properties { if let v = o[name] { out += errors(v, sub, at: path + [name]) } }
            for name in schema.required ?? [] where o[name] == nil { fail("required", .missingField, at: path + [name]) }
            if schema.additionalProperties == false {
                let known = Set(schema.properties.map(\.name))
                let extra = o.keys.filter { !known.contains($0) }
                    .sorted { $0.unicodeScalars.lexicographicallyPrecedes($1.unicodeScalars) }
                if let first = extra.first { fail("unknown field", .extraField, at: path + [first]) }
            }
        }
        if let alternatives = schema.anyOf {
            let each = alternatives.map { errors(value, $0, at: path) }
            if !each.contains(where: \.isEmpty) {
                let context = each.flatMap { $0 }
                out.append(SchemaError(code: context.map(\.code).min()!, path: path,
                                       message: "\(value.canonical) is not valid under any of the given schemas",
                                       context: context))
            }
        }
        for sub in schema.allOf ?? [] { out += errors(value, sub, at: path) }
        if let negated = schema.not.first, errors(value, negated, at: path).isEmpty {
            fail("\(value.canonical) should not be valid under \(negated.json.canonical)")
        }
        if schema.conditional.count == 3, let test = schema.conditional[0] {
            let passes = errors(value, test, at: path).isEmpty
            if let branch = schema.conditional[passes ? 1 : 2] { out += errors(value, branch, at: path) }
        }
        return out
    }

    static func jsonType(_ value: JSONValue) -> String {
        switch value {
        case .null: "null"
        case .bool: "a boolean"
        case .int, .double: "a number"
        case .string: "a string"
        case .array: "an array"
        case .object: "an object"
        }
    }

    /// `jsonschema`'s draft 2020-12 types: a boolean is not a number, and an integral float is an integer.
    static func isType(_ value: JSONValue, _ type: String) -> Bool {
        switch (type, value) {
        case ("null", .null), ("boolean", .bool), ("string", .string), ("array", .array), ("object", .object),
             ("integer", .int), ("number", .int), ("number", .double): true
        case ("integer", .double(let d)): d.isFinite && d.rounded(.towardZero) == d
        default: false
        }
    }

    static func number(_ value: JSONValue) -> Double? {
        switch value {
        case .int(let i): Double(i)
        case .double(let d): d
        default: nil
        }
    }

    /// `jsonschema`'s `equal`: numbers by value (1 equals 1.0), a boolean never equals a number, strings by code
    /// point (as Python compares them).
    static func equal(_ a: JSONValue, _ b: JSONValue) -> Bool {
        switch (a, b) {
        case (.int(let x), .int(let y)): x == y
        case (.int(let x), .double(let y)), (.double(let y), .int(let x)): Double(x) == y
        case (.double(let x), .double(let y)): x == y
        case (.string(let x), .string(let y)): x.unicodeScalars.elementsEqual(y.unicodeScalars)
        case (.array(let x), .array(let y)): x.count == y.count && zip(x, y).allSatisfy { equal($0, $1) }
        case (.object(let x), .object(let y)):
            x.count == y.count && x.allSatisfy { key, v in y[key].map { equal(v, $0) } ?? false }
        default: a == b
        }
    }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var compiled: [String: NSRegularExpression] = [:]

    /// `re.search(pattern, value)`. Python's `$` also matches before a final newline, so a trailing `$` becomes
    /// `(?=\n?\z)` for ICU.
    static func matches(_ value: String, _ pattern: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        let regex: NSRegularExpression
        if let cached = compiled[pattern] {
            regex = cached
        } else {
            let icu = pattern.hasSuffix("$") ? String(pattern.dropLast()) + "(?=\\n?\\z)" : pattern
            regex = try! NSRegularExpression(pattern: icu)
            compiled[pattern] = regex
        }
        return regex.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)) != nil
    }

    /// `date` and `date-time` as `scripts/check_contracts.py` and `siab_ledger.ingest` check them: the shape, then
    /// what Python's `fromisoformat` accepts (year 1 or later, a real day, hour 0-23, minute and second 0-59, an
    /// offset under 24 hours). Any other format is not checked, as in the reference.
    static func isFormat(_ value: String, _ format: String) -> Bool {
        switch format {
        case "date":
            return matches(value, "^[0-9]{4}-[0-9]{2}-[0-9]{2}\\z") && isDate(Array(value.utf8))
        case "date-time":
            let shape = "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})\\z"
            guard matches(value, shape) else { return false }
            let s = Array(value.utf8)
            guard isDate(Array(s[0..<10])), digits(s, 11) <= 23, digits(s, 14) <= 59, digits(s, 17) <= 59 else {
                return false
            }
            return s.last == UInt8(ascii: "Z") || digits(s, s.count - 5) * 60 + digits(s, s.count - 2) < 24 * 60
        default:
            return true
        }
    }

    /// Two ASCII digits at `at`.
    private static func digits(_ s: [UInt8], _ at: Int) -> Int { Int(s[at] - 48) * 10 + Int(s[at + 1] - 48) }

    /// `YYYY-MM-DD`, already shaped.
    private static func isDate(_ s: [UInt8]) -> Bool {
        let year = digits(s, 0) * 100 + digits(s, 2), month = digits(s, 5), day = digits(s, 8)
        guard year >= 1, (1...12).contains(month), day >= 1 else { return false }
        let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)
        return day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    }
}

// MARK: - The cross-field rules

/// `CROSS_CHECKS` of `scripts/check_contracts.py`, as `siab_ledger.ingest` copies them: what a schema cannot say.
/// They run only on a body that passed its schema, so every field has its type.
enum CrossChecks {
    static func check(_ collection: String, _ doc: [String: JSONValue]) -> [String] {
        switch collection {
        case "transaction": transaction(doc)
        case "exception": exception(doc)
        case "allocation": allocation(doc)
        default: []
        }
    }

    private static func string(_ value: JSONValue?) -> String? {
        if case .string(let s)? = value { return s }
        return nil
    }

    private static func ends(_ value: String, with suffix: String) -> Bool {
        value.unicodeScalars.reversed().starts(with: suffix.unicodeScalars.reversed())
    }

    private static func sameSKU(_ doc: [String: JSONValue]) -> String? {
        guard let unit = string(doc["unit_id"]), let sku = string(doc["sku"]),
              !Ledger.skuOf(unit).unicodeScalars.elementsEqual(sku.unicodeScalars) else { return nil }
        return "sku \(sku) is not the SKU part of unit_id \(unit)"
    }

    static func transaction(_ doc: [String: JSONValue]) -> [String] {
        var errors: [String] = []
        if let error = sameSKU(doc) { errors.append(error) }
        if let hlc = string(doc["hlc"]), let device = string(doc["device"]), !ends(hlc, with: "-" + device) {
            errors.append("hlc \(hlc) does not end with the device id \(device)")
        }
        return errors
    }

    static func allocation(_ doc: [String: JSONValue]) -> [String] {
        if let at = string(doc["opened_at"]), let by = string(doc["opened_by"]), !ends(at, with: "-" + by) {
            return ["opened_at \(at) does not end with opened_by \(by)"]
        }
        return []
    }

    static func exception(_ doc: [String: JSONValue]) -> [String] {
        var errors: [String] = []
        if case .array(let txns)? = doc["transactions"] {
            let ids = txns.compactMap(string)
            if ids.count != txns.count
                || !zip(ids, ids.dropFirst()).allSatisfy({ !$1.unicodeScalars.lexicographicallyPrecedes($0.unicodeScalars) }) {
                errors.append("transactions are not sorted")
            }
            if case .array(let branches)? = doc["branches"] {
                let named = branches.compactMap { branch -> JSONValue? in
                    if case .object(let b) = branch { return b["txn"] ?? .null }
                    return nil
                }
                if !SchemaEvaluator.equal(.array(named), .array(txns)) {
                    errors.append("branches[i].txn does not match transactions[i]")
                }
            }
        }
        if let error = sameSKU(doc) { errors.append(error) }
        if let unit = string(doc["unit_id"]), let key = string(doc["dispute_key"]),
           !key.unicodeScalars.starts(with: (unit + "|").unicodeScalars) {
            errors.append("dispute_key \(key) does not start with the unit_id")
        }
        if case .object(let res)? = doc["resolution"], let hlc = string(res["hlc"]), let by = string(res["by"]),
           !ends(hlc, with: "-" + by) {
            errors.append("resolution.hlc \(hlc) does not end with resolution.by \(by)")
        }
        return errors
    }
}
