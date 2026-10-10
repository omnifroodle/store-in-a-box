import SwiftUI

struct CustodyView: View {
    @ObservedObject var model: CustodyViewModel
    let station: ScanStation

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            ModeHeader(text: model.header, detail: "Every scan is accepted; the record is checked afterwards")
            HStack(spacing: 12) {
                ForEach(CustodyMode.allCases) { mode in
                    let selected = model.mode == mode
                    Button { model.mode = mode } label: {
                        Label(mode.title, systemImage: selected ? "checkmark.circle.fill" : "circle")
                            .font(Stage.bodyBold)
                            .frame(maxWidth: .infinity, minHeight: 52)
                    }
                    .buttonStyle(.bordered)
                    .tint(selected ? .accentColor : .secondary)
                    .accessibilityAddTraits(selected ? .isSelected : [])
                    .accessibilityIdentifier("custody-mode-\(mode.rawValue)")
                }
            }
            .frame(maxWidth: 560)
            AdaptiveStack {
                ScannerPanel(station: station) { model.handle(scan: $0) }
                    .frame(maxWidth: 420)
                sessionColumn
            }
        }
        .padding(24)
    }

    private var sessionColumn: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("This session: \(model.session.count)").font(Stage.bodyBold)
                Spacer()
                Button("Clear list") { model.clearSession() }.font(Stage.body).disabled(model.session.isEmpty)
            }
            ScrollView {
                VStack(spacing: 10) {
                    ForEach(model.session) { CustodyLineRow(line: $0) }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct CustodyLineRow: View {
    let line: CustodyLine

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(line.mode.title).font(Stage.bodyBold)
                Text(line.unit).font(Stage.body.monospaced())
                Spacer()
                if line.disagrees { RecordDisagreesTag() }
            }
            Text(allocationText).font(Stage.small).foregroundStyle(.secondary)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
    }

    /// "fills box-07's allocation, opened 14:02:11": an allocation's id is `alloc::<hlc of its opening>`.
    private var allocationText: String {
        guard let allocation = line.allocation else { return "no allocation on record" }
        let opened = allocation.hasPrefix("alloc::") ? ", opened " + Stage.time(hlc: String(allocation.dropFirst(7))) : ""
        return (line.mode == .return_ ? "empties " : "fills ") + "\(line.allocationHolder)'s allocation" + opened
    }
}
