import CouchbaseLiteSwift
import XCTest
@testable import SIABCore

/// Decoding the pairing QR, and keeping the pairing on the device: identity in `local.device`, password in the
/// keychain (an in-memory fake here).
final class PairingTests: XCTestCase {
    final class MemorySecrets: SecretStore {
        var values: [String: String] = [:]
        func secret(for account: String) throws -> String? { values[account] }
        func setSecret(_ secret: String, for account: String) throws { values[account] = secret }
    }

    static let good: [String: Any] = [
        "v": 1, "box": "box-07", "trip": "trip-2026-10-18-riverfest", "device": "tablet-a",
        "edge_url": "ws://192.0.2.10:59840/retail", "user": "tablet-a", "password": "test-only",
        "cert_sha256": NSNull(), "peer_group": "siab-trip-2026-10-18-riverfest",
    ]

    static func text(_ changes: [String: Any] = [:]) -> String {
        let body = good.merging(changes) { $1 }
        return String(decoding: try! JSONSerialization.data(withJSONObject: body), as: UTF8.self)
    }

    var directory: URL!
    var database: Database!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        var config = DatabaseConfiguration()
        config.directory = directory.path
        database = try Database(name: "pairing", config: config)
    }

    override func tearDownWithError() throws {
        try database.delete()
        try? FileManager.default.removeItem(at: directory)
    }

    /// #104: a payload whose ids would trap the HLC, or whose address cannot be replicated to, is refused at decode.
    func testMalformedPairingIsRejectedAtDecode() throws {
        XCTAssertNoThrow(try PairingPayload.decode(Self.text()))
        XCTAssertNoThrow(try PairingPayload.decode(Self.text(["edge_url": "wss://box.local:59840/retail",
                                                              "cert_sha256": String(repeating: "ab", count: 32)])))
        let cases: [(String, Any)] = [
            ("device", "Tablet A"), ("device", ""), ("device", "1tablet"),
            ("box", "Box 07"), ("trip", "riverfest"), ("trip", "trip-2026-10-18-"),
            ("edge_url", "http://192.0.2.10:59840/retail"), ("edge_url", "ws:///retail"), ("edge_url", "not a url"),
            ("user", ""), ("peer_group", ""),
            ("cert_sha256", "AB" + String(repeating: "0", count: 62)), ("cert_sha256", "abc"),
        ]
        for (field, value) in cases {
            XCTAssertThrowsError(try PairingPayload.decode(Self.text([field: value])), "\(field)=\(value)") { error in
                XCTAssertEqual(error as? PairingPayload.Error, .invalid(field: field, value: "\(value)"))
            }
        }
        XCTAssertThrowsError(try PairingPayload.decode("{\"v\": 1}"))  // missing fields: a DecodingError
        XCTAssertThrowsError(try PairingPayload.decode("not json"))
    }

    func testPairingStoreKeepsThePasswordOutOfTheDatabase() throws {
        let secrets = MemorySecrets()
        let store = PairingStore(database: database, secrets: secrets)
        XCTAssertNil(try store.load())

        let pairing = try PairingPayload.decode(Self.text())
        try store.save(pairing)
        XCTAssertEqual(try store.load(), pairing)
        XCTAssertEqual(secrets.values, ["tablet-a": "test-only"])

        let doc = try XCTUnwrap(database.collection(name: "device", scope: "local")?.document(id: "self"))
        XCTAssertNil(doc.value(forKey: "password"))
        XCTAssertFalse(doc.toJSON().contains("test-only"))
        XCTAssertEqual(doc.string(forKey: "edge_url"), pairing.edgeURL)
        // The app's identity reader decodes the same document.
        XCTAssertEqual(try JSONDecoder().decode(DeviceIdentity.self, from: Data(doc.toJSON().utf8)), pairing.identity)

        // Pairing again (a new QR) replaces both halves.
        var next = pairing
        next.edgeURL = "ws://192.0.2.11:59840/retail"
        next.password = "rotated"
        try store.save(next)
        XCTAssertEqual(try store.load(), next)

        // An identity without its password (keychain wiped) is an error, not an empty password.
        secrets.values = [:]
        XCTAssertThrowsError(try store.load()) { error in
            XCTAssertEqual(error as? PairingStore.Failure, .missingPassword(device: "tablet-a"))
        }
    }

    func testPairingStoreRefusesAnInvalidPayload() throws {
        var pairing = try PairingPayload.decode(Self.text())
        pairing.device = "Tablet A"
        let secrets = MemorySecrets()
        XCTAssertThrowsError(try PairingStore(database: database, secrets: secrets).save(pairing))
        XCTAssertEqual(secrets.values, [:])
    }

    /// The real keychain, where the test host allows it. An unhosted test bundle has no keychain entitlement (macOS
    /// `swift test` and the iOS simulator alike) and skips; the app itself uses the keychain in the two-simulator
    /// check.
    func testKeychainSecretStoreRoundTrip() throws {
        let store = KeychainSecretStore(service: "com.example.storeinabox.tests.\(UUID().uuidString)")
        defer {
            SecItemDelete([kSecClass: kSecClassGenericPassword, kSecAttrService: store.service,
                           kSecUseDataProtectionKeychain: true] as CFDictionary)
        }
        let before: String?
        do {
            before = try store.secret(for: "tablet-a")  // macOS reads "not found" without the entitlement
            try store.setSecret("one", for: "tablet-a")
        } catch let failure as KeychainSecretStore.Failure where failure.status == errSecMissingEntitlement {
            throw XCTSkip("no keychain entitlement in this test host")
        }
        XCTAssertNil(before)
        try store.setSecret("two", for: "tablet-a")
        XCTAssertEqual(try store.secret(for: "tablet-a"), "two")
    }
}
