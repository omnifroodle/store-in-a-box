import SwiftUI

struct SellView: View {
    @ObservedObject var model: SellViewModel
    let station: ScanStation
    @State private var failure: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            ModeHeader(text: "SELLING", detail: "Scan each unit into the basket, then take the tender")
            AdaptiveStack {
                ScannerPanel(station: station) { model.add(scan: $0) }
                    .frame(maxWidth: 420)
                basketColumn
            }
        }
        .padding(24)
        .overlay(alignment: .top) { confirmationBanner }
        .animation(.easeInOut, value: model.confirmation)
        .alert("Sale not recorded", isPresented: .constant(failure != nil), presenting: failure) { _ in
            Button("OK") { failure = nil }
        } message: { Text($0) }
    }

    private var basketColumn: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Basket").font(Stage.bodyBold)
            if model.basket.isEmpty {
                Text("Empty: scan a unit label").font(Stage.body).foregroundStyle(.secondary)
            }
            ScrollView {
                VStack(spacing: 10) {
                    ForEach(model.basket) { line in BasketRow(line: line) { model.remove(unit: line.unit) } }
                }
            }
            .frame(minHeight: model.basket.isEmpty ? 0 : 130)
            Divider()
            HStack(alignment: .firstTextBaseline) {
                Text("Total").font(Stage.bodyBold)
                Spacer()
                Text(Stage.money(model.total)).font(Stage.total).accessibilityIdentifier("basket-total")
            }
            HStack(spacing: 16) {
                ForEach(TenderKind.allCases) { kind in
                    Button {
                        do {
                            try model.tender(kind: kind)
                            station.clear()
                        } catch {
                            failure = String(describing: error)
                        }
                    } label: {
                        Text(kind.label).font(Stage.bodyBold).frame(maxWidth: .infinity, minHeight: 56)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.basket.isEmpty)
                    .accessibilityIdentifier("tender-\(kind.rawValue)")
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder private var confirmationBanner: some View {
        if let done = model.confirmation {
            Label("Sold \(done.count) \(done.count == 1 ? "unit" : "units") · \(Stage.money(done.total))",
                  systemImage: "checkmark.seal.fill")
                .font(Stage.header)
                .foregroundStyle(.white)
                .padding(.horizontal, 28)
                .padding(.vertical, 16)
                .background(Color.green.opacity(0.9), in: Capsule())
                .padding(.top, 12)
                .transition(.move(edge: .top).combined(with: .opacity))
                .accessibilityIdentifier("sale-confirmation")
        }
    }
}

private struct BasketRow: View {
    let line: BasketLine
    let remove: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(line.name).font(Stage.bodyBold)
                Text(line.unit).font(Stage.small).foregroundStyle(.secondary)
                if line.disagrees { RecordDisagreesTag() }
            }
            Spacer()
            Text(Stage.money(line.price)).font(Stage.bodyBold).monospacedDigit()
            Button(role: .destructive, action: remove) {
                Label("Remove", systemImage: "minus.circle.fill").labelStyle(.iconOnly).font(.system(size: 28))
            }
            .accessibilityLabel("Remove \(line.unit)")
        }
        .padding(12)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
    }
}
