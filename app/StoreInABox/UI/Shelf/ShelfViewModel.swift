import Combine
import Foundation
import SIABCore

struct ShelfRow: Identifiable, Equatable {
    var id: String { sku }
    let sku: String
    let name: String
    let price: Money?
    /// Units this device holds.
    let here: Int
    /// Units the box holds.
    let box: Int
}

/// Shelf: live counts per SKU for this device and its box. It never refreshes; it follows the ledger state.
@MainActor
final class ShelfViewModel: ObservableObject {
    @Published private(set) var rows: [ShelfRow] = []
    /// Matches a SKU or a product name, ignoring case.
    @Published var filter = "" { didSet { applyFilter() } }
    private var all: [ShelfRow] = []
    private var subscription: AnyCancellable?

    init(store: CustodyStoring, catalog: ProductCatalog) {
        let identity = store.identity
        subscription = store.state.combineLatest(catalog.products)
            .sink { [weak self] state, products in
                self?.all = Self.rows(state: state, products: products, identity: identity)
                self?.applyFilter()
            }
    }

    /// One row per product in the catalog or with any unit in the ledger, by SKU.
    static func rows(state: LedgerState, products: [String: Product], identity: DeviceIdentity) -> [ShelfRow] {
        let skus = Set(products.keys).union(state.units.values.map(\.sku))
        return skus.sorted().map { sku in
            ShelfRow(sku: sku, name: products[sku]?.name ?? sku, price: products[sku]?.price,
                     here: state.counts[CustodianSKU(custodian: identity.device, sku: sku)] ?? 0,
                     box: state.counts[CustodianSKU(custodian: identity.box, sku: sku)] ?? 0)
        }
    }

    private func applyFilter() {
        let needle = filter.trimmingCharacters(in: .whitespaces)
        let shown = needle.isEmpty ? all : all.filter {
            $0.sku.localizedCaseInsensitiveContains(needle) || $0.name.localizedCaseInsensitiveContains(needle)
        }
        if shown != rows { rows = shown }
    }
}
