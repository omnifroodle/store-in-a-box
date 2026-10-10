import SwiftUI

struct ShelfView: View {
    @ObservedObject var model: ShelfViewModel
    let device: String
    let box: String
    @Environment(\.horizontalSizeClass) private var sizeClass
    private var column: CGFloat { sizeClass == .regular ? 190 : 84 }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            ModeHeader(text: "SHELF", detail: "Live counts: \(device) and \(box)")
            TextField("Filter by SKU or name", text: $model.filter)
                .font(Stage.body)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
                .frame(maxWidth: 420)
            HStack {
                Text("Product").frame(maxWidth: .infinity, alignment: .leading)
                Text(sizeClass == .regular ? "Here (\(device))" : "Here").frame(width: column, alignment: .trailing)
                Text(sizeClass == .regular ? "Box (\(box))" : "Box").frame(width: column, alignment: .trailing)
            }
            .font(Stage.small.weight(.semibold))
            .foregroundStyle(.secondary)
            ScrollView {
                LazyVStack(spacing: 8) {
                    ForEach(model.rows) { row in ShelfRowView(row: row, column: column) }
                }
            }
        }
        .padding(24)
        .animation(.spring(duration: 0.4), value: model.rows)
    }
}

private struct ShelfRowView: View {
    let row: ShelfRow
    let column: CGFloat

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(row.name).font(Stage.bodyBold)
                Text(row.sku + (row.price.map { "  ·  " + Stage.money($0) } ?? ""))
                    .font(Stage.small.monospaced())
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            count(row.here, id: "here")
            count(row.box, id: "box")
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("shelf-\(row.sku)")
    }

    private func count(_ value: Int, id: String) -> some View {
        Text("\(value)")
            .font(Stage.count)
            .foregroundStyle(value == 0 ? .secondary : .primary)
            .contentTransition(.numericText(value: Double(value)))
            .frame(width: column, alignment: .trailing)
            .accessibilityIdentifier("shelf-\(row.sku)-\(id)")
    }
}
