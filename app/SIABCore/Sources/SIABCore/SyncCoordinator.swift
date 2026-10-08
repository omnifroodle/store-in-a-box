import Combine
import CouchbaseLiteSwift
import Foundation
import os
import Security

/// The Couchbase Lite edition SIABCore was built against (Package.swift, `SIAB_CBL_EDITION`). Community Edition is the
/// default; the device-to-device mesh (the Multipeer Replicator) needs Enterprise Edition.
public enum CouchbaseEdition: String {
    case community = "Community Edition", enterprise = "Enterprise Edition"

    public static var current: CouchbaseEdition {
        #if COUCHBASE_ENTERPRISE
        .enterprise
        #else
        .community
        #endif
    }

    public var hasMesh: Bool { self == .enterprise }
}

#if COUCHBASE_ENTERPRISE
public typealias MeshIdentity = TLSIdentity
#else
/// Community Edition has no TLS identity for the mesh: uninhabited, so nothing can produce one.
public enum MeshIdentity {}
#endif

/// This device's TLS identity for the device-to-device mesh.
public protocol TLSIdentityProvider { func identity() throws -> MeshIdentity }

/// A self-signed identity created at first launch and kept in the keychain under `label` (Couchbase Lite stores it
/// there); renewed when it has expired. The common name is the device id, which Diagnostics shows for each peer.
public struct KeychainTLSIdentityProvider: TLSIdentityProvider {
    public var label: String
    public var commonName: String
    public init(label: String = "siab-p2p", commonName: String) { self.label = label; self.commonName = commonName }

    public func identity() throws -> MeshIdentity {
        #if COUCHBASE_ENTERPRISE
        if let existing = try TLSIdentity.identity(withLabel: label) {
            if existing.expiration > Date() { return existing }
            try TLSIdentity.deleteIdentity(withLabel: label)
        }
        return try TLSIdentity.createIdentity(for: [.clientAuth, .serverAuth],
                                              attributes: [certAttrCommonName: commonName], label: label)
        #else
        throw CocoaError(.featureUnsupported)
        #endif
    }
}

/// The replicator to the box.
public enum BoxLink: Equatable {
    case connected(String)
    case offline(lastSeenMs: Int64?)
    case error(String)

    /// Edge Server reachable when the replicator is idle or busy. A replicator that stopped on an error (refused
    /// credentials, say) is an error; an error it is retrying through (the box off or out of range) is offline.
    public static func from(activity: Replicator.ActivityLevel, error: String?, url: String,
                            lastSeenMs: Int64?) -> BoxLink {
        switch activity {
        case .idle, .busy: return .connected(url)
        case .stopped: return error.map { .error($0) } ?? .offline(lastSeenMs: lastSeenMs)
        default: return .offline(lastSeenMs: lastSeenMs)
        }
    }
}

/// Document counters for the box replicator, including the unpushed tail (#81): movements the box does not have yet,
/// the oldest of them, and when the last push landed.
public struct BoxDocuments: Equatable {
    public var pushed = 0
    public var pulled = 0
    public var unpushed = 0
    public var oldestUnpushedMs: Int64?
    public var lastPushedMs: Int64?
    public var errors = 0
    public var lastError: String?
    public init() {}

    /// From the replicator's pending ids in `store.transaction` (`txn::<hlc>`, so the hlc gives the time).
    public mutating func setPending(_ ids: Set<String>) {
        unpushed = ids.count
        oldestUnpushedMs = ids.compactMap { HLC(String($0.dropFirst("txn::".count)))?.ms }.min()
    }
}

/// The device-to-device mesh as a whole.
public enum MeshStatus: Equatable {
    case stopped, running
    case unavailable(String)
    case error(String)

    /// From each transport's last status: running while any transport is active (or none has reported yet); an
    /// error only when every transport that reported failed. A failed transport beside a working one (no Bluetooth LE
    /// in the simulator) is a note.
    static func from(_ transports: [String: (active: Bool, error: String?)]) -> (MeshStatus, notes: [String]) {
        let failed = transports.filter { !$0.value.active && $0.value.error != nil }.sorted { $0.key < $1.key }
            .map { "\($0.key): \($0.value.error!)" }
        if !transports.isEmpty, !transports.values.contains(where: \.active), !failed.isEmpty {
            return (.error(failed.joined(separator: "; ")), [])
        }
        return (.running, failed)
    }
}

public struct PeerLink: Identifiable, Equatable {
    public enum State: String { case online, replicating, idle, offline }
    public var id: String
    /// The peer's certificate common name (its device id) when the mesh knows it.
    public var name: String?
    public var state: State
    public var lastSeenMs: Int64
}

/// The two replicators: one continuous push-pull `Replicator` to the box (Couchbase Edge Server) from the pairing
/// payload, and, in Enterprise Edition, one `MultipeerReplicator` mesh with the other devices of the peer group. Both
/// carry exactly the five `store` collections; nothing in `local` is ever added. Nothing waits on either. Call from
/// the main thread.
public final class SyncCoordinator: ObservableObject {
    static let log = Logger(subsystem: "com.example.storeinabox", category: "sync")
    @Published public var box: BoxLink = .offline(lastSeenMs: nil)
    /// The box replicator's last error, transient ones included (cleared when it connects).
    @Published public var boxReason: String?
    @Published public var boxDocuments = BoxDocuments()
    @Published public var mesh: MeshStatus = .stopped
    @Published public var meshNotes: [String] = []
    @Published public var peers: [PeerLink] = []

    public typealias Fetch = (URL) async throws -> Data
    public let pairing: PairingPayload
    let database: Database
    let identityProvider: TLSIdentityProvider
    let clock: Clock
    let fetch: Fetch
    private var replicator: Replicator?
    private var tokens: [ListenerToken] = []
    private var lastSeenMs: Int64?
    private var peerTable: [String: PeerLink] = [:]
    private var transports: [String: (active: Bool, error: String?)] = [:]
    private var generation = 0
    #if COUCHBASE_ENTERPRISE
    private var multipeer: MultipeerReplicator?
    #endif

    public init(database: Database, pairing: PairingPayload, identity: TLSIdentityProvider,
                clock: Clock = SystemClock(), fetch: @escaping Fetch = { try await URLSession.shared.data(from: $0).0 }) {
        self.database = database
        self.pairing = pairing
        self.identityProvider = identity
        self.clock = clock
        self.fetch = fetch
    }

    deinit { stop() }

    // MARK: - Lifecycle

    public func start() {
        stop()
        startMesh()
        guard let expected = pairing.certSHA256 else { return startBox(pinned: nil) }
        guard let agent = pairing.agentURL else { return box = .error("no box agent address in the pairing payload") }
        let started = generation
        Task { @MainActor in
            do {
                let pem = try await fetch(agent.appendingPathComponent("cert.pem"))
                guard started == generation else { return }  // stopped (or restarted) while fetching
                guard let cert = Replication.pinnedCertificate(pem: pem, expected: expected) else {
                    return box = .error("the box certificate does not match the pairing QR")
                }
                startBox(pinned: cert)
            } catch {
                if started == generation { box = .error("could not fetch the box certificate: \(error.localizedDescription)") }
            }
        }
    }

    public func stop() {
        generation += 1
        tokens.forEach { $0.remove() }
        tokens = []
        replicator?.stop()
        replicator = nil
        #if COUCHBASE_ENTERPRISE
        multipeer?.stop()
        multipeer = nil
        #endif
        if case .running = mesh { mesh = .stopped }
        transports = [:]
        meshNotes = []
    }

    private func startBox(pinned: SecCertificate?) {
        do {
            let replicator = Replicator(config: try Replication.boxConfiguration(database, pairing: pairing, pinned: pinned))
            tokens.append(replicator.addChangeListener(withQueue: .main) { [weak self] change in
                self?.boxChanged(change.status)
            })
            tokens.append(replicator.addDocumentReplicationListener(withQueue: .main) { [weak self] replication in
                self?.documentsReplicated(push: replication.isPush, replication.documents.map { ($0.id, $0.error) })
            })
            self.replicator = replicator
            replicator.start()
            refreshPending()
        } catch {
            box = .error(error.localizedDescription)
        }
    }

    private func startMesh() {
        #if COUCHBASE_ENTERPRISE
        do {
            let multipeer = try MultipeerReplicator(config: Replication.meshConfiguration(
                database, pairing: pairing, identity: identityProvider.identity()))
            tokens.append(multipeer.addPeerDiscoveryStatusListener(on: .main) { [weak self, weak multipeer] status in
                self?.peerChanged(status.peerID.description, status.online ? .online : .offline,
                                  name: multipeer.flatMap { Self.commonName($0, status.peerID) })
            })
            tokens.append(multipeer.addPeerReplicatorStatusListener(on: .main) { [weak self, weak multipeer] status in
                let busy = status.status.activity == .busy || status.status.activity == .connecting
                self?.peerChanged(status.peerID.description, busy ? .replicating : .idle,
                                  name: multipeer.flatMap { Self.commonName($0, status.peerID) })
            })
            tokens.append(multipeer.addStatusListener(on: .main) { [weak self] status in
                guard let transport = status.transport else { return }  // the per-transport events say it all
                self?.transportChanged(transport == .bluetooth ? "Bluetooth LE" : "Wi-Fi", active: status.active,
                                       error: status.error?.localizedDescription)
            })
            self.multipeer = multipeer
            multipeer.start()
            mesh = .running
            Self.log.info("mesh started, peer group \(self.pairing.peerGroup, privacy: .public)")
        } catch {
            mesh = .error(error.localizedDescription)
            Self.log.error("mesh did not start: \(error.localizedDescription, privacy: .public)")
        }
        #else
        mesh = .unavailable(CouchbaseEdition.current.rawValue)
        #endif
    }

    #if COUCHBASE_ENTERPRISE
    private static func commonName(_ multipeer: MultipeerReplicator, _ peer: PeerID) -> String? {
        multipeer.peerInfo(for: peer)?.certificate.flatMap { SecCertificateCopySubjectSummary($0) as String? }
    }
    #endif

    // MARK: - Listener state (internal for tests)

    func boxChanged(_ status: Replicator.Status) {
        if status.activity == .idle || status.activity == .busy { lastSeenMs = clock.nowMs() }
        box = BoxLink.from(activity: status.activity, error: status.error?.localizedDescription,
                           url: pairing.edgeURL, lastSeenMs: lastSeenMs)
        if case .connected = box { boxReason = nil } else if let error = status.error { boxReason = error.localizedDescription }
        Self.log.info("box \(String(describing: self.box), privacy: .public)")
        refreshPending()
    }

    /// The box replicator's per-document listener: counts, and the last per-document error (#81).
    func documentsReplicated(push: Bool, _ documents: [(id: String, error: Error?)]) {
        var docs = boxDocuments
        for doc in documents {
            if let error = doc.error {
                docs.errors += 1
                docs.lastError = "\(doc.id): \(error.localizedDescription)"
            } else if push {
                docs.pushed += 1
                docs.lastPushedMs = clock.nowMs()
            } else {
                docs.pulled += 1
            }
        }
        boxDocuments = docs
        refreshPending()
    }

    /// Re-reads the unpushed tail. The replicator's listeners call it; so does the app after a local write, since an
    /// offline replicator reports no change when a movement joins the tail.
    public func refreshPending() {
        guard let replicator, let txns = try? database.collection(name: "transaction", scope: CustodyStore.storeScope),
              let pending = try? replicator.pendingDocumentIds(collection: txns) else { return }
        boxDocuments.setPending(pending)
    }

    func transportChanged(_ name: String, active: Bool, error: String?) {
        transports[name] = (active, error)
        (mesh, meshNotes) = MeshStatus.from(transports)
        Self.log.info("mesh \(name, privacy: .public) active=\(active) \(error ?? "", privacy: .public)")
    }

    func peerChanged(_ id: String, _ state: PeerLink.State, name: String? = nil) {
        peerTable[id] = PeerLink(id: id, name: name ?? peerTable[id]?.name, state: state, lastSeenMs: clock.nowMs())
        peers = peerTable.values.sorted { $0.id < $1.id }
        Self.log.info("peer \(id, privacy: .public) \(name ?? "", privacy: .public) \(state.rawValue, privacy: .public)")
    }
}
