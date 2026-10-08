import CouchbaseLiteSwift
import Foundation
import Security

/// Where the Edge Server password lives. The app uses the keychain; tests use an in-memory fake.
public protocol SecretStore {
    func secret(for account: String) throws -> String?
    func setSecret(_ secret: String, for account: String) throws
}

/// Generic passwords in the keychain, this device only, readable after first unlock (the app syncs in the background
/// of a sale, never before the device has been unlocked once).
public struct KeychainSecretStore: SecretStore {
    public struct Failure: Error, Equatable { public let status: OSStatus }
    public var service: String
    public init(service: String = "com.example.storeinabox.edge-password") { self.service = service }

    private func query(_ account: String) -> [CFString: Any] {
        [kSecClass: kSecClassGenericPassword, kSecAttrService: service, kSecAttrAccount: account,
         kSecUseDataProtectionKeychain: true]
    }

    public func secret(for account: String) throws -> String? {
        var q = query(account)
        q[kSecReturnData] = true
        q[kSecMatchLimit] = kSecMatchLimitOne
        var out: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &out)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = out as? Data else { throw Failure(status: status) }
        return String(decoding: data, as: UTF8.self)
    }

    public func setSecret(_ secret: String, for account: String) throws {
        let data = Data(secret.utf8)
        var status = SecItemUpdate(query(account) as CFDictionary, [kSecValueData: data] as CFDictionary)
        if status == errSecItemNotFound {
            var add = query(account)
            add[kSecValueData] = data
            add[kSecAttrAccessible] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            status = SecItemAdd(add as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw Failure(status: status) }
    }
}

/// This device's pairing: the identity and the non-secret pairing fields in `local.device` (never replicated), the
/// Edge Server password in the `SecretStore` (the keychain), keyed by the device id.
public struct PairingStore {
    public static let documentID = "self"
    public enum Failure: Error, Equatable { case missingPassword(device: String) }

    /// The `local.device` document. A superset of `DeviceIdentity`, which decodes from it as well.
    struct Stored: Codable {
        var device, box, trip, store: String
        var v: Int
        var edgeURL, user: String
        var certSHA256: String?
        var peerGroup: String
        enum CodingKeys: String, CodingKey {
            case device, box, trip, store, v, edgeURL = "edge_url", user, certSHA256 = "cert_sha256",
                 peerGroup = "peer_group"
        }
    }

    let database: Database
    let secrets: SecretStore

    public init(database: Database, secrets: SecretStore = KeychainSecretStore()) {
        self.database = database
        self.secrets = secrets
    }

    private func collection() throws -> Collection {
        try CustodyStore.prepare(database)
        return try database.collection(name: "device", scope: CustodyStore.localScope)!
    }

    /// Validates, then writes the password first so a stored identity always has its password.
    public func save(_ pairing: PairingPayload) throws {
        try pairing.validate()
        try secrets.setSecret(pairing.password, for: pairing.device)
        let stored = Stored(device: pairing.device, box: pairing.box, trip: pairing.trip, store: Custodian.store,
                            v: pairing.v, edgeURL: pairing.edgeURL, user: pairing.user,
                            certSHA256: pairing.certSHA256, peerGroup: pairing.peerGroup)
        let json = String(decoding: try JSONEncoder().encode(stored), as: UTF8.self)
        try collection().save(document: MutableDocument(id: Self.documentID, json: json))
    }

    /// nil when this device has never paired.
    public func load() throws -> PairingPayload? {
        guard let doc = try collection().document(id: Self.documentID) else { return nil }
        let s = try JSONDecoder().decode(Stored.self, from: Data(doc.toJSON().utf8))
        guard let password = try secrets.secret(for: s.device) else { throw Failure.missingPassword(device: s.device) }
        let pairing = PairingPayload(v: s.v, box: s.box, trip: s.trip, device: s.device, edgeURL: s.edgeURL,
                                     user: s.user, password: password, certSHA256: s.certSHA256,
                                     peerGroup: s.peerGroup)
        try pairing.validate()
        return pairing
    }
}
