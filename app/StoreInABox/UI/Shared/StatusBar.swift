import SIABCore
import SwiftUI

/// The words the status bar shows, from the sync coordinator's state.
enum StatusText {
    static func box(_ link: BoxLink, name: String) -> String {
        switch link {
        case .connected: "\(name) connected"
        case .offline(let seen): "\(name) offline" + (seen.map { " since \(clock($0))" } ?? "")
        case .error: "\(name) link error"
        }
    }

    /// `peers`: each known peer's state; offline peers are not counted.
    static func peers(_ mesh: MeshStatus, _ peers: [PeerLink.State]) -> String {
        switch mesh {
        case .running:
            let count = peers.filter { $0 != .offline }.count
            return count == 1 ? "1 peer" : "\(count) peers"
        case .unavailable: return "no mesh"
        case .stopped: return "mesh stopped"
        case .error: return "mesh error"
        }
    }

    static func clock(_ ms: Int64) -> String {
        Date(timeIntervalSince1970: Double(ms) / 1000).formatted(.dateTime.hour().minute())
    }
}

/// On every screen: the box link, the peer count and this device's id. The gear opens Diagnostics.
struct StatusBar: View {
    @ObservedObject var sync: SyncCoordinator
    let device: String
    let openDiagnostics: () -> Void

    var body: some View {
        // One line on an iPad; two on a phone, rather than truncating.
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 24) { link; peers; Spacer(minLength: 8); deviceAndGear }
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 16) { link; Spacer(minLength: 0) }
                HStack(spacing: 16) { peers; Spacer(minLength: 8); deviceAndGear }
            }
        }
        .font(Stage.status)
        .lineLimit(1)
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(.bar)
    }

    private var link: some View {
        Label(StatusText.box(sync.box, name: sync.pairing.box), systemImage: boxIcon)
            .fixedSize()
            .accessibilityIdentifier("status-box")
    }

    private var peers: some View {
        Label(StatusText.peers(sync.mesh, sync.peers.map(\.state)), systemImage: "point.3.connected.trianglepath.dotted")
            .fixedSize()
            .accessibilityIdentifier("status-peers")
    }

    private var deviceAndGear: some View {
        HStack(spacing: 16) {
            Label(device, systemImage: "ipad.landscape").fixedSize().accessibilityIdentifier("status-device")
            Button(action: openDiagnostics) {
                Image(systemName: "gearshape.fill").font(.system(size: 26))
            }
            .accessibilityLabel("Diagnostics")
            .accessibilityIdentifier("open-diagnostics")
        }
    }

    private var boxIcon: String {
        if case .connected = sync.box { return "shippingbox.fill" }
        return "wifi.slash"
    }
}
