import CouchbaseLiteSwift
import CryptoKit
import Foundation
import Security

/// The replicators' configurations, built from the pairing payload. Both carry exactly the five `store` collections;
/// nothing in `local` is ever added. (The live `SyncCoordinator` that starts them and reports their state is the
/// follow-up to this package.)
public enum Replication {
    public static func replicatedCollections(_ db: Database) throws -> [Collection] {
        try CustodyStore.prepare(db)
        return try CustodyStore.replicatedCollections.map { try db.collection(name: $0, scope: CustodyStore.storeScope)! }
    }

    /// One continuous push-pull replicator to the box (Couchbase Edge Server), basic auth from the pairing payload,
    /// pinned to the box's certificate when it runs TLS.
    public static func boxConfiguration(_ db: Database, pairing: PairingPayload,
                                        pinned: SecCertificate?) throws -> ReplicatorConfiguration {
        guard let url = URL(string: pairing.edgeURL) else { throw URLError(.badURL) }
        var config = ReplicatorConfiguration(
            collections: CollectionConfiguration.fromCollections(try replicatedCollections(db)), target: URLEndpoint(url: url))
        config.replicatorType = .pushAndPull
        config.continuous = true
        config.authenticator = BasicAuthenticator(username: pairing.user, password: pairing.password)
        config.pinnedServerCertificate = pinned
        return config
    }

    /// The device-to-device mesh: the peer group from the pairing payload, Wi-Fi and Bluetooth LE.
    public static func meshConfiguration(_ db: Database, pairing: PairingPayload,
                                         identity: TLSIdentity) throws -> MultipeerReplicatorConfiguration {
        // Phase 0: any peer presenting a certificate; Phase 1 pins the box-vended CA.
        let authenticator = MultipeerCertificateAuthenticator { _, certs in !certs.isEmpty }
        var config = try MultipeerReplicatorConfiguration(
            peerGroupID: pairing.peerGroup, identity: identity, authenticator: authenticator,
            collections: meshCollections(db))
        config.transports = [.wifi, .bluetooth]
        return config
    }

    public static func meshCollections(_ db: Database) throws -> [MultipeerCollectionConfiguration] {
        MultipeerCollectionConfiguration.fromCollections(try replicatedCollections(db))
    }

    /// The certificate to pin, from the box agent's `/cert.pem`, only if the sha256 of its DER is `expected`.
    public static func pinnedCertificate(pem: Data, expected: String) -> SecCertificate? {
        let body = String(decoding: pem, as: UTF8.self).split(whereSeparator: \.isNewline)
            .filter { !$0.hasPrefix("-----") }.joined()
        guard let der = Data(base64Encoded: body) else { return nil }
        let digest = SHA256.hash(data: der).map { String(format: "%02x", $0) }.joined()
        guard digest == expected.lowercased() else { return nil }
        return SecCertificateCreateWithData(nil, der as CFData)
    }
}
