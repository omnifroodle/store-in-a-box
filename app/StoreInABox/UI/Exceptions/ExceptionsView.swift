import SIABCore
import SwiftUI

struct ExceptionsView: View {
    @ObservedObject var model: ExceptionsViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            ModeHeader(text: "EXCEPTIONS: \(model.disputes.count) OPEN", detail: "Read only. HQ resolves.")
            if model.disputes.isEmpty {
                Label("No open disputes", systemImage: "checkmark.circle").font(Stage.body).foregroundStyle(.secondary)
            }
            ScrollView {
                VStack(spacing: 16) {
                    ForEach(model.disputes) { DisputeCard(row: $0) }
                }
            }
        }
        .padding(24)
        .animation(.default, value: model.disputes)
    }
}

private struct DisputeCard: View {
    let row: DisputeRow

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Label(row.title, systemImage: row.isFork ? "arrow.triangle.branch" : "exclamationmark.triangle.fill")
                    .font(Stage.bodyBold)
                Text(row.unit).font(Stage.body.monospaced())
                Spacer()
                Text(row.kind.rawValue).font(Stage.small.monospaced()).foregroundStyle(.secondary)
            }
            if let note = row.note { Text(note).font(Stage.body) }
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 12) { sides }
                VStack(alignment: .leading, spacing: 12) { sides }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityIdentifier("dispute-\(row.id)")
    }

    private var sides: some View {
        ForEach(row.sides) { SideView(side: $0) }
    }
}

private struct SideView: View {
    let side: DisputeRow.Side

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(roleText).font(Stage.small.weight(.semibold)).foregroundStyle(.secondary)
            Text(side.device).font(Stage.bodyBold)
            Text(side.kind.rawValue.replacingOccurrences(of: "_", with: " ")).font(Stage.body)
            Text("\(side.from) → \(side.to)").font(Stage.small.monospaced())
            Text(Stage.time(hlc: side.hlc)).font(Stage.small.monospacedDigit())
        }
        .padding(12)
        .frame(minWidth: 240, alignment: .leading)
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(.secondary.opacity(0.6), lineWidth: 1))
    }

    private var roleText: String {
        switch side.role {
        case .branch: "Branch"
        case .flagged: "Flagged movement"
        case .before: "Record before it"
        }
    }
}
