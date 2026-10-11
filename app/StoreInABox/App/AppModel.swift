import Combine
import CouchbaseLiteSwift
import Foundation
import os
import SIABCore

/// The composition root: opens the database, loads the pairing and wires SIABCore's services (the custody store and
/// the sync coordinator), then registers the screens and the scanner (WS6) over them.
@MainActor
final class AppModel: ObservableObject {
    static let log = Logger(subsystem: "com.example.storeinabox", category: "ledger")
    @Published private(set) var identity: DeviceIdentity?
    @Published private(set) var state: LedgerState = .empty(store: Custodian.store)
    @Published private(set) var sync: SyncCoordinator?
    @Published private(set) var problem: String?
    /// Sell, Shelf, Custody, Exceptions and the scanner; nil until this device is paired.
    @Published private(set) var screens: Screens?
    private(set) var database: Database?
    private(set) var custody: CustodyStore?
    private var pairings: PairingStore?
    private var catalog: StoreProductCatalog?
    private var subscriptions: Set<AnyCancellable> = []

    init() {
        // Hosting StoreInABoxTests: open nothing, so no unit test starts a replicator or touches the app's database
        // (a simulator that was paired by hand would otherwise sync during the tests).
        if ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil { return }
        do {
            let database = try Database(name: "storeinabox")
            try CustodyStore.prepare(database)
            self.database = database
            catalog = StoreProductCatalog(database: database)
            let pairings = PairingStore(database: database)
            self.pairings = pairings
            if let pairing = try pairings.load() { try start(pairing) }
        } catch {
            problem = String(describing: error)
        }
        #if DEBUG
        // Scripted simulator checks pair at launch, as a paste would:
        // `SIMCTL_CHILD_SIAB_PAIRING='<payload>' xcrun simctl launch <device> com.example.storeinabox`.
        if identity == nil, let text = ProcessInfo.processInfo.environment["SIAB_PAIRING"] { pair(text) }
        #endif
    }

    /// Pairs this device from the box's QR text (scanned or pasted): refuses a malformed payload, stores the identity
    /// in `local.device` and the password in the keychain, then (re)starts custody and sync under it.
    func pair(_ text: String) {
        do {
            let pairing = try PairingPayload.decode(text.trimmingCharacters(in: .whitespacesAndNewlines))
            try pairings?.save(pairing)
            try start(pairing)
            problem = nil
        } catch {
            problem = "Pairing refused: \(error)"
        }
    }

    private func start(_ pairing: PairingPayload) throws {
        guard let database, let catalog else { return }
        sync?.stop()
        subscriptions = []
        let custody = try CustodyStore(database: database, identity: pairing.identity, clock: SystemClock())
        let sync = SyncCoordinator(database: database, pairing: pairing,
                                   identity: KeychainTLSIdentityProvider(commonName: pairing.device))
        custody.state
            .receive(on: DispatchQueue.main)
            .sink { [weak self, weak custody, weak sync] state in
                self?.state = state
                let counts = state.counts.sorted { $0.key < $1.key }.map { "\($0.key.custodian) \($0.key.sku)=\($0.value)" }
                Self.log.info("counts \(counts.joined(separator: ", "), privacy: .public)")
                _ = try? custody?.detectAndWriteExceptions()  // writes only documents it has not written before
                sync?.refreshPending()
            }
            .store(in: &subscriptions)
        self.custody = custody
        self.sync = sync
        identity = pairing.identity
        screens = Screens(store: custody, catalog: catalog)
        sync.start()
    }

    /// Diagnostics' "Rebuild derived state": re-reduces every movement and rewrites `local.unit_state`.
    func rebuild() {
        do { _ = try custody?.rebuild() } catch { problem = "Rebuild failed: \(error)" }
    }

    /// Diagnostics' movement check (the mesh and box checks): pack a unit onto the box, or take it from the box.
    func check(_ unit: String, take: Bool) {
        guard let custody, let identity else { return }
        do {
            if take {
                try custody.checkOut(unit: unit, from: identity.box, to: identity.device)
            } else {
                try custody.checkOut(unit: unit, from: identity.store, to: identity.box, actingFor: identity.box)
            }
        } catch {
            problem = "Check-out failed: \(error)"
        }
    }
}
