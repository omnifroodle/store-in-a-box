import CouchbaseLiteSwift
import XCTest
@testable import SIABCore

/// SyncCoordinator's configuration and listener state, with no box and no peers: the replicators are built, never
/// started (the live paths are the two-simulator and owner-present checks).
final class SyncCoordinatorTests: XCTestCase {
    struct NoIdentity: TLSIdentityProvider {
        func identity() throws -> TLSIdentity { throw CocoaError(.featureUnsupported) }
    }

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
        database = try Database(name: "sync", config: config)
        try CustodyStore.prepare(database)
    }

    override func tearDownWithError() throws {
        try database.delete()
        try? FileManager.default.removeItem(at: directory)
    }

    func testBoxLinkFollowsTheReplicator() {
        let url = Self.pairing.edgeURL
        XCTAssertEqual(BoxLink.from(activity: .idle, error: nil, url: url, lastSeenMs: 5), .connected(url))
        XCTAssertEqual(BoxLink.from(activity: .busy, error: nil, url: url, lastSeenMs: 5), .connected(url))
        XCTAssertEqual(BoxLink.from(activity: .offline, error: nil, url: url, lastSeenMs: 5), .offline(lastSeenMs: 5))
        XCTAssertEqual(BoxLink.from(activity: .connecting, error: nil, url: url, lastSeenMs: nil), .offline(lastSeenMs: nil))
        XCTAssertEqual(BoxLink.from(activity: .busy, error: "401", url: url, lastSeenMs: 5), .error("401"))
    }

    func testUnpushedTailFromPendingIDs() {
        var docs = BoxDocuments()
        docs.setPending(["txn::1792330920000-0000-tablet-a", "txn::1792330800000-0003-tablet-a", "not-a-txn"])
        XCTAssertEqual(docs.unpushed, 3)
        XCTAssertEqual(docs.oldestUnpushedMs, 1_792_330_800_000)
        docs.setPending([])
        XCTAssertEqual(docs.unpushed, 0)
        XCTAssertNil(docs.oldestUnpushedMs)
    }

    func testPeersKeepLastSeenUnderTheFakeClock() {
        let clock = FakeClock()
        let sync = SyncCoordinator(database: database, pairing: Self.pairing, identity: NoIdentity(), clock: clock)
        sync.peerChanged("peer-b", .online)
        clock.advance(4_000)
        sync.peerChanged("peer-a", .replicating)
        clock.advance(1_000)
        sync.peerChanged("peer-b", .offline)
        XCTAssertEqual(sync.peers, [PeerLink(id: "peer-a", state: .replicating, lastSeenMs: clock.ms - 1_000),
                                    PeerLink(id: "peer-b", state: .offline, lastSeenMs: clock.ms)])
    }

    @MainActor
    func testCertificateMismatchIsAnErrorNotACrash() async throws {
        var pairing = Self.pairing
        pairing.certSHA256 = String(repeating: "0", count: 64)
        var fetched: [URL] = []
        let sync = SyncCoordinator(database: database, pairing: pairing, identity: NoIdentity(), clock: FakeClock(),
                                   fetch: { url in fetched.append(url); return Data(ReplicationTests.pem.utf8) })
        sync.start()
        for _ in 0..<100 where sync.box == .offline(lastSeenMs: nil) { await Task.yield() }
        sync.stop()
        XCTAssertEqual(fetched.map(\.absoluteString), ["http://192.0.2.10:8787/cert.pem"])
        XCTAssertEqual(sync.box, .error("the box certificate does not match the pairing QR"))
    }
}
