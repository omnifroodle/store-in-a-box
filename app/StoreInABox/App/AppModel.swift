import Combine
import CouchbaseLiteSwift
import Foundation
import SIABCore

/// The composition root: opens the database and wires SIABCore's services. Kept small so WS6 can register its
/// screens here without touching SIABCore.
@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var identity: DeviceIdentity?
    @Published private(set) var state: LedgerState = .empty(store: Custodian.store)
    @Published private(set) var problem: String?
    private(set) var database: Database?
    private(set) var custody: CustodyStore?
    private var subscriptions: Set<AnyCancellable> = []

    init() {
        do {
            let database = try Database(name: "storeinabox")
            try CustodyStore.prepare(database)
            self.database = database
            if let identity = try Self.storedIdentity(database) { try start(identity) }
        } catch {
            problem = error.localizedDescription
        }
    }

    /// This device's identity, written to `local.device` when it pairs (never replicated).
    static func storedIdentity(_ database: Database) throws -> DeviceIdentity? {
        guard let doc = try database.collection(name: "device", scope: CustodyStore.localScope)?.document(id: "self")
        else { return nil }
        return try JSONDecoder().decode(DeviceIdentity.self, from: Data(doc.toJSON().utf8))
    }

    func start(_ identity: DeviceIdentity) throws {
        guard let database else { return }
        let custody = try CustodyStore(database: database, identity: identity, clock: SystemClock())
        custody.state
            .receive(on: DispatchQueue.main)
            .sink { [weak self, weak custody] state in
                self?.state = state
                _ = try? custody?.detectAndWriteExceptions()  // writes only documents it has not written before
            }
            .store(in: &subscriptions)
        self.custody = custody
        self.identity = identity
    }
}
