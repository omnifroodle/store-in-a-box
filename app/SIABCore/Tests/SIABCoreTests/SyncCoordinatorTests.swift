import CouchbaseLiteSwift
import XCTest
@testable import SIABCore

/// SyncCoordinator's configuration and listener state, with no box and no peers. The only replicator started points
/// at a closed loopback port (no network); the live paths are the two-simulator and owner-present checks.
final class SyncCoordinatorTests: XCTestCase {
    /// Counts calls; never produces an identity (Community Edition has none to produce).
    final class NoIdentity: TLSIdentityProvider {
        var calls = 0
        func identity() throws -> MeshIdentity { calls += 1; throw CocoaError(.featureUnsupported) }
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
        let drained = expectation(description: "main queue drained")
        DispatchQueue.main.async { drained.fulfill() }
        wait(for: [drained], timeout: 10)
        try database.delete()
        try? FileManager.default.removeItem(at: directory)
    }

    func testBoxLinkFollowsTheReplicator() {
        let url = Self.pairing.edgeURL
        XCTAssertEqual(BoxLink.from(activity: .idle, error: nil, url: url, lastSeenMs: 5), .connected(url))
        XCTAssertEqual(BoxLink.from(activity: .busy, error: nil, url: url, lastSeenMs: 5), .connected(url))
        XCTAssertEqual(BoxLink.from(activity: .offline, error: nil, url: url, lastSeenMs: 5), .offline(lastSeenMs: 5))
        XCTAssertEqual(BoxLink.from(activity: .connecting, error: nil, url: url, lastSeenMs: nil), .offline(lastSeenMs: nil))
        // Retrying through an error (the box is off) is offline; stopped on one (refused credentials) is an error.
        XCTAssertEqual(BoxLink.from(activity: .offline, error: "Connection refused", url: url, lastSeenMs: 5),
                       .offline(lastSeenMs: 5))
        XCTAssertEqual(BoxLink.from(activity: .stopped, error: "401", url: url, lastSeenMs: 5), .error("401"))
        XCTAssertEqual(BoxLink.from(activity: .stopped, error: nil, url: url, lastSeenMs: 5), .offline(lastSeenMs: 5))
    }

    /// A transport that fails beside a working one is a note (no Bluetooth LE in the simulator); the mesh is an error
    /// only when every transport that reported failed.
    func testMeshStatusFromTransports() {
        XCTAssertEqual(MeshStatus.from([:]).0, .running)
        let wifiUp = MeshStatus.from(["Wi-Fi": (true, nil), "Bluetooth LE": (false, "not supported")])
        XCTAssertEqual(wifiUp.0, .running)
        XCTAssertEqual(wifiUp.notes, ["Bluetooth LE: not supported"])
        let none = MeshStatus.from(["Wi-Fi": (false, "no network"), "Bluetooth LE": (false, "not supported")])
        XCTAssertEqual(none.0, .error("Bluetooth LE: not supported; Wi-Fi: no network"))
        XCTAssertEqual(none.notes, [])

        let sync = SyncCoordinator(database: database, pairing: Self.pairing, identity: NoIdentity(), clock: FakeClock())
        sync.transportChanged("Bluetooth LE", active: false, error: "not supported")
        XCTAssertEqual(sync.mesh, .error("Bluetooth LE: not supported"))
        sync.transportChanged("Wi-Fi", active: true, error: nil)
        XCTAssertEqual(sync.mesh, .running)
        XCTAssertEqual(sync.meshNotes, ["Bluetooth LE: not supported"])
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
        sync.peerChanged("peer-b", .online, name: "tablet-b")
        clock.advance(4_000)
        sync.peerChanged("peer-a", .replicating)
        clock.advance(1_000)
        sync.peerChanged("peer-b", .offline)
        XCTAssertEqual(sync.peers, [PeerLink(id: "peer-a", name: nil, state: .replicating, lastSeenMs: clock.ms - 1_000),
                                    PeerLink(id: "peer-b", name: "tablet-b", state: .offline, lastSeenMs: clock.ms)])
    }

    func testPerDocumentErrorsAndPushTimes() {
        let clock = FakeClock()
        let sync = SyncCoordinator(database: database, pairing: Self.pairing, identity: NoIdentity(), clock: clock)
        sync.documentsReplicated(push: true, [("txn::a", nil), ("txn::b", nil)])
        let pushedAt = clock.ms
        clock.advance(60_000)
        sync.documentsReplicated(push: true, [("txn::c", CocoaError(.fileWriteNoPermission))])
        sync.documentsReplicated(push: false, [("txn::d", nil)])
        XCTAssertEqual(sync.boxDocuments.pushed, 2)
        XCTAssertEqual(sync.boxDocuments.pulled, 1)
        XCTAssertEqual(sync.boxDocuments.errors, 1)
        XCTAssertEqual(sync.boxDocuments.lastPushedMs, pushedAt)
        XCTAssertTrue(sync.boxDocuments.lastError?.hasPrefix("txn::c: ") ?? false)
    }

    /// A movement written while the box is unreachable joins the unpushed tail, with its own hlc as the oldest.
    func testLocalWriteJoinsTheUnpushedTail() throws {
        var pairing = Self.pairing
        pairing.edgeURL = "ws://127.0.0.1:9/retail"  // discard port, nothing listens: offline, no network
        let clock = FakeClock()
        let identity = NoIdentity()
        let sync = SyncCoordinator(database: database, pairing: pairing, identity: identity, clock: clock)
        sync.start()
        defer { sync.stop() }
        let custody = try CustodyStore(database: database, identity: pairing.identity, clock: clock)
        let txn = try custody.checkOut(unit: "JKT-RAIN-M-BLU#001", from: Custodian.store, to: "box-07", actingFor: "box-07")
        sync.refreshPending()
        XCTAssertEqual(sync.boxDocuments.unpushed, 1)
        XCTAssertEqual(sync.boxDocuments.oldestUnpushedMs, HLC(String(txn.id.dropFirst(5)))?.ms)
        #if COUCHBASE_ENTERPRISE
        XCTAssertEqual(identity.calls, 1)
        XCTAssertEqual(sync.mesh, .error(CocoaError(.featureUnsupported).localizedDescription))
        #else
        XCTAssertEqual(identity.calls, 0, "Community Edition never asks for a mesh identity")
        XCTAssertEqual(sync.mesh, .unavailable("Community Edition"))
        XCTAssertEqual(CouchbaseEdition.current, .community)
        #endif
        XCTAssertEqual(sync.peers, [])
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

    /// `stop()` while the certificate is being fetched: the late answer starts nothing and reports nothing.
    @MainActor
    func testStopDuringCertificateFetchStartsNothing() async throws {
        var pairing = Self.pairing
        pairing.certSHA256 = ReplicationTests.fingerprint
        let gate = AsyncStream<Void>.makeStream()
        var fetching = false
        let sync = SyncCoordinator(database: database, pairing: pairing, identity: NoIdentity(), clock: FakeClock(),
                                   fetch: { _ in
                                       fetching = true
                                       for await _ in gate.stream { break }
                                       return Data(ReplicationTests.pem.utf8)
                                   })
        sync.start()
        for _ in 0..<100 where !fetching { await Task.yield() }
        XCTAssertTrue(fetching)
        sync.stop()
        gate.continuation.yield()
        for _ in 0..<100 { await Task.yield() }
        XCTAssertEqual(sync.box, .offline(lastSeenMs: nil))
        sync.refreshPending()
        XCTAssertEqual(sync.boxDocuments, BoxDocuments(), "no replicator was started")
    }
}
