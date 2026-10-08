import CouchbaseLiteSwift
import XCTest
@testable import SIABCore

/// The replicators' configurations, built and inspected, never started (no box, no peers).
final class ReplicationTests: XCTestCase {
    /// A throwaway self-signed certificate (its key was discarded), and the sha256 of its DER.
    static let pem = """
    -----BEGIN CERTIFICATE-----
    MIIBhDCCASugAwIBAgIUT4/QtGdni3kyGZ4d/9hs++js5ngwCgYIKoZIzj0EAwIw
    GDEWMBQGA1UEAwwNc2lhYi10ZXN0LWJveDAeFw0yNjEwMDgxODU4MzdaFw0zNjEw
    MDUxODU4MzdaMBgxFjAUBgNVBAMMDXNpYWItdGVzdC1ib3gwWTATBgcqhkjOPQIB
    BggqhkjOPQMBBwNCAAQO70mnarbfHQi3TPiXjNUWnsSqcq+NQvvg6+7/tRpxK8Q1
    ZjeDFh0k1CMvgxzJNlQmaicfqC+wbXfS0cn0Upovo1MwUTAdBgNVHQ4EFgQUwMl8
    l/dnQyEt9B00obxa26F2aNowHwYDVR0jBBgwFoAUwMl8l/dnQyEt9B00obxa26F2
    aNowDwYDVR0TAQH/BAUwAwEB/zAKBggqhkjOPQQDAgNHADBEAiBvHpzdymPsM2iJ
    K7WLHfVeyTgVyjCYGb9piFlnqKszoAIgdbrb27QZwi5JKoFtFSMEOE0JUrn9eHdc
    osKLMjhirrY=
    -----END CERTIFICATE-----
    """
    static let fingerprint = "11aec4aaf85bfbab1f1529f98da1e4140cfc354774ab726ce070955111641929"

    static let pairing = PairingPayload(
        v: 1, box: "box-07", trip: "trip-2026-10-18-riverfest", device: "tablet-a",
        edgeURL: "ws://192.0.2.10:59840/retail", user: "tablet-a", password: "test-only", certSHA256: nil,
        peerGroup: "siab-trip-2026-10-18-riverfest")

    var directory: URL!
    var database: Database!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        var config = DatabaseConfiguration()
        config.directory = directory.path
        database = try Database(name: "replication", config: config)
        try CustodyStore.prepare(database)
    }

    override func tearDownWithError() throws {
        try database.close()
        try Database.delete(withName: "replication", inDirectory: directory.path)
    }

    func testLocalScopeIsNotInAnyReplicatorConfig() throws {
        let box = try Replication.boxConfiguration(database, pairing: Self.pairing, pinned: nil).collections
            .map { "\($0.collection.scope.name).\($0.collection.name)" }.sorted()
        let mesh = try Replication.meshCollections(database)
            .map { "\($0.collection.scope.name).\($0.collection.name)" }.sorted()
        let expected = ["store.allocation", "store.exception", "store.product", "store.transaction", "store.trip"]
        XCTAssertEqual(box, expected)
        XCTAssertEqual(mesh, expected)
        XCTAssertFalse((box + mesh).contains { $0.hasPrefix("local.") })
        // The local scope exists on the device all the same.
        XCTAssertEqual(try database.scope(name: "local")?.collections().map(\.name).sorted(), ["device", "unit_state"])
    }

    func testBoxConfigurationFromPairing() throws {
        let config = try Replication.boxConfiguration(database, pairing: Self.pairing, pinned: nil)
        XCTAssertEqual((config.target as? URLEndpoint)?.url.absoluteString, "ws://192.0.2.10:59840/retail")
        XCTAssertTrue(config.continuous)
        XCTAssertEqual(config.replicatorType, .pushAndPull)
        XCTAssertEqual((config.authenticator as? BasicAuthenticator)?.username, "tablet-a")
        XCTAssertNil(config.pinnedServerCertificate)

        let cert = try XCTUnwrap(Replication.pinnedCertificate(pem: Data(Self.pem.utf8), expected: Self.fingerprint))
        let pinned = try Replication.boxConfiguration(database, pairing: Self.pairing, pinned: cert)
        XCTAssertNotNil(pinned.pinnedServerCertificate)
    }

    func testPinnedCertificateMustMatchTheFingerprint() {
        let pem = Data(Self.pem.utf8)
        XCTAssertNotNil(Replication.pinnedCertificate(pem: pem, expected: Self.fingerprint))
        XCTAssertNotNil(Replication.pinnedCertificate(pem: pem, expected: Self.fingerprint.uppercased()))
        XCTAssertNil(Replication.pinnedCertificate(pem: pem, expected: String(repeating: "0", count: 64)))
        XCTAssertNil(Replication.pinnedCertificate(pem: Data("not a pem".utf8), expected: Self.fingerprint))
    }
}
