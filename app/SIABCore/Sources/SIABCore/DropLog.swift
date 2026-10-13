import CouchbaseLiteSwift
import CryptoKit
import Foundation
import os

/// One entry of a node's drop log (decision 010): a `Drop`, where the node got the document when it knows
/// (`local`, `box` or `peer` on a tablet), and when it was first and last dropped (RFC 3339, the node's clock).
public struct DropRecord: Equatable, Codable {
    public var id: String
    public var collection: String
    public var code: DropCode
    public var detail: String
    public var source: String?
    public var firstSeen: String
    public var lastSeen: String

    enum CodingKeys: String, CodingKey {
        case id, collection, code, detail, source, firstSeen = "first_seen", lastSeen = "last_seen"
    }

    public init(_ drop: Drop, source: String?, firstSeen: String, lastSeen: String) {
        id = drop.id; collection = drop.collection; code = drop.code; detail = drop.detail
        self.source = source; self.firstSeen = firstSeen; self.lastSeen = lastSeen
    }

    /// `local.drop_log`'s document id, one per `(collection, id)`: `drop::` and the sha256 (hex) of the UTF-8 of
    /// `<collection>::<id>`. Bounded (70 ASCII bytes, under Couchbase Lite's 240-byte id limit, whatever the dropped
    /// document's id) and exact on code points: two ids that differ only by Unicode normalisation are two
    /// documents in Couchbase Lite and in the reference, so they are two entries here. The real `id` and
    /// `collection` are in the body.
    public var key: String { Self.key(collection: collection, id: id) }

    static func key(collection: String, id: String) -> String {
        "drop::" + SHA256.hash(data: Data("\(collection)::\(id)".utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

/// `local.drop_log` (never replicated): at most `limit` entries, one per `(collection, id)`, the oldest `lastSeen`
/// evicted first. A document dropped again on every rebuild updates its entry's `lastSeen` (and code and detail)
/// only; each new entry is logged once at warning. Best effort: nothing the log does (a read, a write, the disk)
/// fails a rebuild.
final class DropLog {
    static let limit = 200
    static let log = Logger(subsystem: "com.example.storeinabox", category: "ledger")

    let database: Database
    let collection: Collection
    /// Test seam: runs inside the log's write batch.
    var beforeWrite: (() throws -> Void)?
    /// The write failures already logged (each distinct message once).
    private(set) var failuresLogged: Set<String> = []

    init(database: Database, collection: Collection) {
        self.database = database
        self.collection = collection
    }

    /// Every entry in the log.
    func entries() throws -> [DropRecord] {
        let query = try database.createQuery("SELECT META().id AS id FROM `\(CustodyStore.localScope)`.`drop_log`")
        return try query.execute().allResults().compactMap { row in
            guard let id = row.string(forKey: "id"), let doc = try collection.document(id: id) else { return nil }
            return try? JSONDecoder().decode(DropRecord.self, from: Data(doc.toJSON().utf8))
        }
    }

    /// Records one rebuild's `drops` at `now` and returns their entries, newest `lastSeen` first. A drop the log has
    /// no room for (more than `limit` at once) is returned unstored and not logged, so the count stays exact and the
    /// log does not churn: the entries it already holds are kept before new ones of the same age. Never throws:
    /// when the log cannot be read or written, the drops are still returned (counted and shown) and the failure is
    /// logged once.
    func record(_ drops: [Drop], now: String, source: (Drop) -> String) -> [DropRecord] {
        var held: [String: DropRecord] = [:]
        do {
            held = Dictionary(try entries().map { ($0.key, $0) }, uniquingKeysWith: { a, _ in a })
        } catch {
            failed("read", error)
        }
        var current: [DropRecord] = []
        var fresh: Set<String> = []
        for drop in drops {
            let key = DropRecord.key(collection: drop.collection, id: drop.id)
            if var entry = held[key] {
                entry.code = drop.code; entry.detail = drop.detail; entry.lastSeen = now
                held[key] = entry
                current.append(entry)
            } else {
                let entry = DropRecord(drop, source: source(drop), firstSeen: now, lastSeen: now)
                held[key] = entry
                fresh.insert(key)
                current.append(entry)
            }
        }
        // Oldest lastSeen first; at the same age, new entries before held ones, then by key.
        let order = held.values.sorted {
            ($0.lastSeen, fresh.contains($0.key) ? 0 : 1, $0.key) < ($1.lastSeen, fresh.contains($1.key) ? 0 : 1, $1.key)
        }
        let evicted = Set(order.prefix(max(0, held.count - Self.limit)).map(\.key))
        let touched = Set(current.map(\.key))
        do {
            try database.inBatch {
                try beforeWrite?()
                for key in evicted where !fresh.contains(key) {
                    if let doc = try collection.document(id: key) { try collection.delete(document: doc) }
                }
                for key in touched.subtracting(evicted) {
                    let json = String(decoding: try JSONEncoder().encode(held[key]!), as: UTF8.self)
                    if let existing = try collection.document(id: key) {
                        try collection.save(document: existing.toMutable().setJSON(json))
                    } else {
                        try collection.save(document: MutableDocument(id: key, json: json))
                    }
                }
            }
            for key in fresh.subtracting(evicted).sorted() {
                let e = held[key]!
                Self.log.warning("""
                    dropped \(e.collection, privacy: .public) \(e.id, privacy: .public): \(e.code.rawValue, privacy: .public), \
                    \(e.detail, privacy: .public) (source \(e.source ?? "unknown", privacy: .public))
                    """)
            }
        } catch {
            failed("write", error)
        }
        return current.sorted { ($1.lastSeen, $0.key) < ($0.lastSeen, $1.key) }
    }

    private func failed(_ what: String, _ error: Error) {
        let message = "the drop log could not \(what): \(error)"
        guard !failuresLogged.contains(message) else { return }
        failuresLogged.insert(message)
        Self.log.error("\(message, privacy: .public); the drops are still counted and shown")
    }
}
