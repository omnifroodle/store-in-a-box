import SIABCore
import SwiftUI

/// The one screen of the data layer (WS6 keeps it behind a gear icon): who this device is, the box link and its
/// unpushed tail, the mesh and its peers, the live counts, pairing and "Rebuild derived state".
struct DiagnosticsView: View {
    @EnvironmentObject var model: AppModel
    @State private var pairing = false

    var body: some View {
        List {
            Section("Device") {
                if let identity = model.identity {
                    LabeledContent("Device", value: identity.device)
                    LabeledContent("Trip", value: identity.trip)
                    LabeledContent("Box", value: identity.box)
                } else {
                    Text("Not paired")
                }
                LabeledContent("Couchbase Lite", value: CouchbaseEdition.current.rawValue)
                if let problem = model.problem {
                    Text(problem).foregroundStyle(.red).accessibilityIdentifier("problem")
                }
            }
            if let sync = model.sync {
                SyncSections(sync: sync)
            }
            Section("Counts") {
                let keys = model.state.counts.keys.sorted()
                if keys.isEmpty { Text("No movements yet").foregroundStyle(.secondary) }
                ForEach(keys, id: \.self) { key in
                    LabeledContent("\(key.custodian)  \(key.sku)", value: "\(model.state.counts[key] ?? 0)")
                }
                LabeledContent("Movements", value: "\(model.state.transactions.count)")
                LabeledContent("Forks", value: "\(model.state.forks.count)")
            }
            DroppedSection(drops: model.drops)
            Section {
                Button("Pair with a box") { pairing = true }
                Button("Rebuild derived state") { model.rebuild() }.disabled(model.identity == nil)
            }
            if model.identity != nil { MovementCheck() }
        }
        .navigationTitle("Diagnostics")
        .sheet(isPresented: $pairing) {
            PairingSheet { text in
                model.pair(text)
                pairing = false
            }
        }
    }
}

/// The box link and the mesh, observed straight from the coordinator so its updates redraw only these rows.
private struct SyncSections: View {
    @ObservedObject var sync: SyncCoordinator

    var body: some View {
        Section("Box") {
            LabeledContent("Link", value: boxLink)
            let docs = sync.boxDocuments
            LabeledContent("Documents", value: "pushed \(docs.pushed), pulled \(docs.pulled), errors \(docs.errors)")
            Text(unpushed(docs)).accessibilityIdentifier("unpushed")
            if let last = docs.lastPushedMs { Text("last pushed \(Clock24.string(last))") }
            if let error = docs.lastError { Text(error).font(.footnote).foregroundStyle(.red) }
        }
        Section("Mesh") {
            Text("mesh: \(mesh)").accessibilityIdentifier("mesh")
            ForEach(sync.meshNotes, id: \.self) { Text($0).font(.footnote).foregroundStyle(.secondary) }
            ForEach(sync.peers) { peer in
                LabeledContent(peer.name ?? peer.id,
                               value: "\(peer.state.rawValue), last seen \(Clock24.string(peer.lastSeenMs, seconds: true))")
            }
        }
    }

    private var boxLink: String {
        switch sync.box {
        case .connected(let url): "connected \(url)"
        case .offline(let seen): "offline" + (seen.map { ", last seen \(Clock24.string($0))" } ?? "")
            + (sync.boxReason.map { " (\($0))" } ?? "")
        case .error(let message): "error: \(message)"
        }
    }

    private var mesh: String {
        switch sync.mesh {
        case .running: "running, \(sync.peers.filter { $0.state != .offline }.count) peers"
        case .stopped: "stopped"
        case .unavailable(let why): "unavailable (\(why))"
        case .error(let message): "error: \(message)"
        }
    }

    private func unpushed(_ docs: BoxDocuments) -> String {
        "unpushed: \(docs.unpushed) movements" + (docs.oldestUnpushedMs.map { " (oldest \(Clock24.string($0)))" } ?? "")
    }
}

/// Pack a unit onto the box, or take it from the box to this device: the movement the mesh and box checks watch
/// arrive on the other devices.
private struct MovementCheck: View {
    @EnvironmentObject var model: AppModel
    @State private var unit = "JKT-RAIN-M-BLU#001"

    var body: some View {
        Section("Movement check") {
            TextField("Unit (SKU#serial)", text: $unit)
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()
            let valid = unit.range(of: "^[A-Z0-9]+(-[A-Z0-9]+)*#[0-9]{3}$", options: .regularExpression) != nil
            Button("Pack onto the box") { model.check(unit, take: false) }.disabled(!valid)
            Button("Take from the box") { model.check(unit, take: true) }.disabled(!valid)
            #if DEBUG
            Button("Drop check: write a v 2 take") { model.writeNewerSchemaMovement(unit) }.disabled(!valid)
            #endif
        }
    }
}

/// Rule 0's drops (decision 010), never a plain pass: how many documents this device could not reduce, then the
/// newest ten in words, with where each came from and when it was last seen.
struct DroppedSection: View {
    let drops: [DropRecord]
    static let shown = 10

    var body: some View {
        Section("Dropped documents") {
            Text(Self.count(drops.count)).accessibilityIdentifier("dropped")
            ForEach(drops.prefix(Self.shown), id: \.key) { drop in
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(drop.collection) \(drop.id)").font(.callout.monospaced())
                    Text(Self.line(drop)).font(.footnote).foregroundStyle(.secondary)
                }
                .accessibilityElement(children: .combine)
            }
        }
    }

    static func count(_ n: Int) -> String { "dropped: \(n) documents" }

    /// `<code in words> · <source> · <HH:mm>`; the words are HQ's, so both screens say the same thing.
    static func line(_ drop: DropRecord) -> String {
        let at = Self.parse(drop.lastSeen).map { Clock24.string(Int64($0.timeIntervalSince1970 * 1000)) } ?? drop.lastSeen
        return [drop.code.words, drop.source ?? "unknown", at].joined(separator: " · ")
    }

    private static func parse(_ rfc3339: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: rfc3339) ?? ISO8601DateFormatter().date(from: rfc3339)
    }
}

enum Clock24 {
    static func string(_ ms: Int64, seconds: Bool = false) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = seconds ? "HH:mm:ss" : "HH:mm"
        return formatter.string(from: Date(timeIntervalSince1970: Double(ms) / 1000))
    }
}
