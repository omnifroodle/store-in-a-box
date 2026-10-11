import Foundation
import SIABCore

/// The four screens and the scanner, built over one custody store and the catalog (AppModel registers them).
@MainActor
struct Screens {
    let identity: DeviceIdentity
    let scanner: ScanStation
    let sell: SellViewModel
    let shelf: ShelfViewModel
    let custody: CustodyViewModel
    let exceptions: ExceptionsViewModel

    init(store: CustodyStoring, catalog: ProductCatalog) {
        identity = store.identity
        scanner = ScanStation(catalog: catalog)
        sell = SellViewModel(store: store, catalog: catalog)
        shelf = ShelfViewModel(store: store, catalog: catalog)
        custody = CustodyViewModel(store: store)
        exceptions = ExceptionsViewModel(store: store)
    }
}
