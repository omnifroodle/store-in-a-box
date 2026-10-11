import SwiftUI

struct SellView: View {
    @ObservedObject var model: SellViewModel
    let station: ScanStation
    @State private var failure: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            ModeHeader(text: "SELLING", detail: "Scan each unit into the basket, then take the tender")
            // In the flow under the header, never over it (#119 item 3): the mode stays named while it shows.
            if let done = model.confirmation { confirmationBanner(done) }
            AdaptiveStack {
                ScannerPanel(station: station) { model.add(scan: $0) }
                    .frame(maxWidth: 420)
                basketColumn
            }
        }
        .padding(24)
        .animation(.easeInOut, value: model.confirmation)
        .alert("Sale not recorded", isPresented: .constant(failure != nil), presenting: failure) { _ in
            Button("OK") { failure = nil }
        } message: { Text($0) }
    }

    private var basketColumn: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Basket").font(Stage.bodyBold)
            if model.basket.isEmpty {
                Text("Empty: scan a unit label").font(Stage.body).foregroundStyle(Stage.muted)
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

    private func confirmationBanner(_ done: SaleConfirmation) -> some View {
        Label("Sold \(done.count) \(done.count == 1 ? "unit" : "units") · \(Stage.money(done.total))",
              systemImage: "checkmark.seal.fill")
            .font(Stage.header)
            .foregroundStyle(.white)
            .padding(.horizontal, 28)
            .padding(.vertical, 14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Stage.confirmed, in: RoundedRectangle(cornerRadius: 16))
            .transition(.move(edge: .top).combined(with: .opacity))
            .accessibilityIdentifier("sale-confirmation")
    }
}

private struct BasketRow: View {
    let line: BasketLine
    let remove: () -> Void

    /// The name, price and remove button on the first line; the unit and the tag each get the row's full width
    /// below, so neither wraps in an iPad's portrait column (#119 item 4).
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 12) {
                Text(line.name).font(Stage.bodyBold)
                Spacer(minLength: 8)
                Text(Stage.money(line.price)).font(Stage.bodyBold).monospacedDigit()
                Button(role: .destructive, action: remove) {
                    Label("Remove", systemImage: "minus.circle.fill").labelStyle(.iconOnly).font(.system(size: 28))
                }
                .accessibilityLabel("Remove \(line.unit)")
            }
            Text(line.unit).font(Stage.small).foregroundStyle(Stage.muted).lineLimit(1).minimumScaleFactor(0.7)
            if line.disagrees { RecordDisagreesTag() }
        }
        .padding(12)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
    }
}
