import Combine
import Foundation
import SIABCore

struct BasketLine: Identifiable, Equatable {
    var id: UnitID { unit }
    let unit: UnitID
    let sku: String
    let name: String
    let price: Money
    /// The record does not have this unit held by this device or its box (rule 8 flags the sale; it stands).
    let disagrees: Bool
}

/// The tenders shown at the till (decision D6). Nothing is charged.
enum TenderKind: String, CaseIterable, Identifiable {
    case cash, card_simulated

    var id: String { rawValue }
    var label: String { self == .cash ? "Cash" : "Card (simulated)" }
    var kind: Tender.Kind { self == .cash ? .cash : .cardSimulated }
}

struct SaleConfirmation: Equatable {
    let count: Int
    let total: Money
}

enum SellError: Error, Equatable { case emptyBasket }

/// Sell: scan units into a basket, pick a tender. One `sale` per unit, all in one batch, sharing one basket id.
@MainActor
final class SellViewModel: ObservableObject {
    static let confirmationSeconds: TimeInterval = 2
    @Published private(set) var basket: [BasketLine] = []
    @Published private(set) var confirmation: SaleConfirmation?
    private let store: CustodyStoring
    private let catalog: ProductCatalog
    private let scheduler: Scheduling
    private var confirmations = 0

    init(store: CustodyStoring, catalog: ProductCatalog, scheduler: Scheduling = MainQueueScheduler()) {
        self.store = store
        self.catalog = catalog
        self.scheduler = scheduler
    }

    var total: Money {
        Money(cents: basket.reduce(0) { $0 + $1.price.cents }, currency: basket.first?.price.currency ?? "USD")
    }

    /// Adds a unit, or says why not: it is already in the basket, or its SKU is not in the catalog. A unit the
    /// record places elsewhere is added with the "record disagrees" tag, never refused.
    @discardableResult
    func add(scan: ScanResult) -> Result<String, ScanRejection> {
        guard !basket.contains(where: { $0.unit == scan.unit }) else { return .failure(.sameUnitTwice(scan.unit)) }
        guard let product = catalog.current[scan.sku] else { return .failure(.unknownSKU(scan.sku)) }
        let disagrees = RecordCheck.saleDisagrees(scan.unit, state: store.currentState, identity: store.identity)
        basket.append(BasketLine(unit: scan.unit, sku: scan.sku, name: product.name, price: product.price,
                                 disagrees: disagrees))
        confirmation = nil
        return .success("\(product.name) \(Stage.money(product.price))")
    }

    func remove(unit: UnitID) {
        basket.removeAll { $0.unit == unit }
    }

    /// Sells every line in one batch: the same new basket id on each sale, the line's price, and a tender of
    /// `kind` for the basket's total. On success the basket clears and the confirmation shows for two seconds. On
    /// failure nothing was written and the basket stays.
    func tender(kind: TenderKind) throws {
        guard !basket.isEmpty else { throw SellError.emptyBasket }
        let lines = basket
        let total = total
        let basketID = UUID().uuidString.lowercased()
        let tender = Tender(kind: kind.kind, amount: total)
        let store = store
        try store.inBatch {
            for line in lines {
                try store.sell(unit: line.unit, tender: tender, price: line.price, basket: basketID)
            }
        }
        basket = []
        confirmation = SaleConfirmation(count: lines.count, total: total)
        confirmations += 1
        let shown = confirmations
        scheduler.after(Self.confirmationSeconds) { [weak self] in
            if self?.confirmations == shown { self?.confirmation = nil }
        }
    }
}
