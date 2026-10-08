import Foundation

/// One row per SKU: does the ledger agree with what the store released (CC5; reference:
/// src/siab_ledger/conservation.py). `openingOnHand`, `received` and `storeOnHand` are nil at the venue.
public struct ConservationRow: Equatable {
    public var sku: String
    public var openingOnHand: Int?
    public var received: Int?
    public var leftStore: Int
    public var untraced: Int
    public var returnedToStore: Int
    public var storeOnHand: Int?
    public var inCustody: [String: Int]
    public var sold: Int
    public var disputed: Int
    public var holds: Bool
}

extension Ledger {
    /// Rows sorted by sku. `inventory` is the store's inventory documents (HQ side), or nil at the venue, where the
    /// rows cover the SKUs in the ledger; with inventory they cover the SKUs in the ledger or the inventory.
    public static func conservation(state: LedgerState, store: String, inventory: [Inventory]?) -> [ConservationRow] {
        var books: [String: Inventory]?
        if let inventory {
            var byStore: [String: Inventory] = [:]
            for doc in inventory.sorted(by: { ($0.id ?? "") < ($1.id ?? "") }) where doc.store == store {
                byStore[doc.sku] = doc
            }
            books = byStore
        }
        var unitsBySKU: [String: [String]] = [:]
        for (unitID, unit) in state.units { unitsBySKU[unit.sku, default: []].append(unitID) }
        let skus = Set(unitsBySKU.keys).union(books.map { Array($0.keys) } ?? [])

        return skus.sorted().map { sku in
            let unitIDs = unitsBySKU[sku] ?? []
            let untraced = unitIDs.filter(state.untraced.contains).count
            var returned = 0, sold = 0, disputed = 0
            var inCustody: [String: Int] = [:]
            for unitID in unitIDs {
                let unit = state.units[unitID]!
                switch unit.state {
                case .sold: sold += 1
                case .disputed: disputed += 1
                case .held where unit.holder == store: returned += 1  // untraced units included (0.4.0)
                case .held: inCustody[unit.holder!, default: 0] += 1
                }
            }
            let leftStore = unitIDs.count - untraced
            var opening: Int?, received: Int?, onHand: Int?
            var holds = untraced == 0
            if let books {
                opening = books[sku]?.openingOnHand ?? 0
                received = books[sku]?.received ?? 0
                onHand = opening! + received! - leftStore + returned
                holds = holds && onHand! >= 0
            }
            return ConservationRow(sku: sku, openingOnHand: opening, received: received, leftStore: leftStore,
                                   untraced: untraced, returnedToStore: returned, storeOnHand: onHand,
                                   inCustody: inCustody, sold: sold, disputed: disputed, holds: holds)
        }
    }
}
