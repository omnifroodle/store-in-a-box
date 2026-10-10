import Foundation

/// The box's pairing QR (ports/box-agent.md, "Pairing payload"). WS3 produces it; WS4 parses it.
public struct PairingPayload: Codable, Equatable {
    public var v: Int
    public var box: String
    public var trip: String
    public var device: String
    public var edgeURL: String
    public var user: String
    public var password: String
    /// Lower-case hex sha256 of the DER of Edge Server's certificate; nil when the box runs without TLS.
    public var certSHA256: String?
    public var peerGroup: String

    enum CodingKeys: String, CodingKey {
        case v, box, trip, device, edgeURL = "edge_url", user, password, certSHA256 = "cert_sha256",
             peerGroup = "peer_group"
    }

    public enum Error: Swift.Error, Equatable {
        case unsupportedVersion(Int)
        /// A field that does not match its pattern (contracts/schemas/common.schema.json for the ids).
        case invalid(field: String, value: String)
    }

    /// Parses the QR text. A reader refuses a version it does not know, and a payload whose ids or addresses are
    /// malformed: they become the device's HLC, custodian and replication target, so they are checked here rather
    /// than on the first write (#104).
    public static func decode(_ text: String) throws -> PairingPayload {
        let payload = try JSONDecoder().decode(PairingPayload.self, from: Data(text.utf8))
        guard payload.v == 1 else { throw Error.unsupportedVersion(payload.v) }
        try payload.validate()
        return payload
    }

    public func validate() throws {
        func check(_ field: String, _ value: String, _ ok: Bool) throws {
            if !ok { throw Error.invalid(field: field, value: value) }
        }
        try check("device", device, HLC.isDeviceID(device))
        try check("box", box, HLC.isDeviceID(box))
        try check("trip", trip, trip.range(of: #"^trip-[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+$"#,
                                            options: .regularExpression) != nil)
        let url = URLComponents(string: edgeURL)
        try check("edge_url", edgeURL, ["ws", "wss"].contains(url?.scheme) && !(url?.host ?? "").isEmpty)
        try check("user", user, !user.isEmpty)
        try check("peer_group", peerGroup, !peerGroup.isEmpty)
        if let cert = certSHA256 {
            try check("cert_sha256", cert, cert.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil)
        }
    }

    public var identity: DeviceIdentity { DeviceIdentity(device: device, box: box, trip: trip) }

    /// The box agent (`GET /cert.pem`): the Edge Server host on the agent's default port, plain HTTP.
    public var agentURL: URL? {
        guard var parts = URLComponents(string: edgeURL) else { return nil }
        parts.scheme = "http"
        parts.port = 8787
        parts.path = ""
        return parts.url
    }
}
