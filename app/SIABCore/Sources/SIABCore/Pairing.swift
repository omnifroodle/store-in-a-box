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

    public enum Error: Swift.Error, Equatable { case unsupportedVersion(Int) }

    /// Parses the QR text. A reader refuses a version it does not know.
    public static func decode(_ text: String) throws -> PairingPayload {
        let payload = try JSONDecoder().decode(PairingPayload.self, from: Data(text.utf8))
        guard payload.v == 1 else { throw Error.unsupportedVersion(payload.v) }
        return payload
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
