import Combine
import CouchbaseLiteSwift
import Foundation
import Security

/// This device's TLS identity for the device-to-device mesh.
public protocol TLSIdentityProvider { func identity() throws -> TLSIdentity }

/// A self-signed identity created at first launch and kept in the keychain under `label`.
public struct KeychainTLSIdentityProvider: TLSIdentityProvider {
    public var label: String
    public var commonName: String
    public init(label: String = "siab-p2p", commonName: String) { self.label = label; self.commonName = commonName }
    public func identity() throws -> TLSIdentity {
        if let existing = try TLSIdentity.identity(withLabel: label) { return existing }
        return try TLSIdentity.createIdentity(for: [.clientAuth, .serverAuth],
                                              attributes: [certAttrCommonName: commonName], label: label)
    }
}

/// The replicator to the box.
public enum BoxLink: Equatable {
    case connected(String)
    case offline(lastSeenMs: Int64?)
    case error(String)

    /// Edge Server reachable when the replicator is idle or busy; offline otherwise; any error wins.
    public static func from(activity: Replicator.ActivityLevel, error: String?, url: String,
                            lastSeenMs: Int64?) -> BoxLink {
        if let error { return .error(error) }
        switch activity {
        case .idle, .busy: return .connected(url)
        default: return .offline(lastSeenMs: lastSeenMs)
        }
    }
}

/// Document counters for the box replicator, including the unpushed tail (#81): this device's movements not yet
/// pushed, the oldest of them, and when the last push landed.
public struct BoxDocuments: Equatable {
    public var pushed = 0
    public var pulled = 0
    public var unpushed = 0
    public var oldestUnpushedMs: Int64?
    public var lastPushedMs: Int64?
    public var lastError: String?
    public init() {}

    /// From the replicator's pending ids in `store.transaction` (`txn::<hlc>`, so the hlc gives the time).
    public mutating func setPending(_ ids: Set<String>) {
        unpushed = ids.count
        oldestUnpushedMs = ids.compactMap { HLC(String($0.dropFirst("txn::".count)))?.ms }.min()
    }
}

public struct PeerLink: Identifiable, Equatable {
    public enum State: String { case online, replicating, idle, offline }
    public var id: String
    public var state: State
    public var lastSeenMs: Int64
}

/// The two replicators: one continuous push-pull `Replicator` to the box (Couchbase Edge Server) from the pairing
/// payload, and one `MultipeerReplicator` mesh with the other devices of the peer group. Both carry exactly the
/// five `store` collections; nothing in `local` is ever added. Nothing waits on either.
public final class SyncCoordinator: ObservableObject {
    @Published public var box: BoxLink = .offline(lastSeenMs: nil)
    @Published public var boxDocuments = BoxDocuments()
    @Published public var peers: [PeerLink] = []

    public typealias Fetch = (URL) async throws -> Data
    let database: Database
    let pairing: PairingPayload
    let identityProvider: TLSIdentityProvider
    let clock: Clock
    let fetch: Fetch
    private var replicator: Replicator?
    private var mesh: MultipeerReplicator?
    private var tokens: [ListenerToken] = []
    private var lastSeenMs: Int64?
    private var peerTable: [String: PeerLink] = [:]

    public init(database: Database, pairing: PairingPayload, identity: TLSIdentityProvider,
                clock: Clock = SystemClock(), fetch: @escaping Fetch = { try await URLSession.shared.data(from: $0).0 }) {
        self.database = database
        self.pairing = pairing
        self.identityProvider = identity
        self.clock = clock
        self.fetch = fetch
    }

    // MARK: - Lifecycle

    public func start() {
        stop()
        startMesh()
        guard let expected = pairing.certSHA256 else { return startBox(pinned: nil) }
        guard let agent = pairing.agentURL else { return box = .error("no box agent address in the pairing payload") }
        Task { @MainActor in
            do {
                let pem = try await fetch(agent.appendingPathComponent("cert.pem"))
                guard let cert = Replication.pinnedCertificate(pem: pem, expected: expected) else {
                    return box = .error("the box certificate does not match the pairing QR")
                }
                startBox(pinned: cert)
            } catch {
                box = .error("could not fetch the box certificate: \(error.localizedDescription)")
            }
        }
    }

    public func stop() {
        tokens.forEach { $0.remove() }
        tokens = []
        replicator?.stop()
        mesh?.stop()
        replicator = nil
        mesh = nil
    }

    private func startBox(pinned: SecCertificate?) {
        do {
            let replicator = Replicator(config: try Replication.boxConfiguration(database, pairing: pairing, pinned: pinned))
            tokens.append(replicator.addChangeListener(withQueue: .main) { [weak self] change in
                self?.boxChanged(change.status)
            })
            tokens.append(replicator.addDocumentReplicationListener(withQueue: .main) { [weak self] replication in
                self?.documentsReplicated(replication)
            })
            self.replicator = replicator
            replicator.start()
        } catch {
            box = .error(error.localizedDescription)
        }
    }

    private func startMesh() {
        do {
            let mesh = try MultipeerReplicator(config: Replication.meshConfiguration(
                database, pairing: pairing, identity: identityProvider.identity()))
            tokens.append(mesh.addPeerDiscoveryStatusListener(on: .main) { [weak self] status in
                self?.peerChanged(status.peerID.description, status.online ? .online : .offline)
            })
            tokens.append(mesh.addPeerReplicatorStatusListener(on: .main) { [weak self] status in
                let busy = status.status.activity == .busy || status.status.activity == .connecting
                self?.peerChanged(status.peerID.description, busy ? .replicating : .idle)
            })
            self.mesh = mesh
            mesh.start()
        } catch {
            peers = [PeerLink(id: "mesh error: \(error.localizedDescription)", state: .offline, lastSeenMs: clock.nowMs())]
        }
    }

    // MARK: - Listener state (internal for tests)

    func boxChanged(_ status: Replicator.Status) {
        if status.activity == .idle || status.activity == .busy { lastSeenMs = clock.nowMs() }
        box = BoxLink.from(activity: status.activity, error: status.error?.localizedDescription,
                           url: pairing.edgeURL, lastSeenMs: lastSeenMs)
        refreshPending()
    }

    func documentsReplicated(_ replication: DocumentReplication) {
        var docs = boxDocuments
        for doc in replication.documents {
            if let error = doc.error {
                docs.lastError = "\(doc.id): \(error.localizedDescription)"
            } else if replication.isPush {
                docs.pushed += 1
                docs.lastPushedMs = clock.nowMs()
            } else {
                docs.pulled += 1
            }
        }
        boxDocuments = docs
        refreshPending()
    }

    private func refreshPending() {
        guard let replicator, let txns = try? database.collection(name: "transaction", scope: CustodyStore.storeScope),
              let pending = try? replicator.pendingDocumentIds(collection: txns) else { return }
        boxDocuments.setPending(pending)
    }

    func peerChanged(_ id: String, _ state: PeerLink.State) {
        peerTable[id] = PeerLink(id: id, state: state, lastSeenMs: clock.nowMs())
        peers = peerTable.values.sorted { $0.id < $1.id }
    }
}
