import Combine
import CouchbaseLiteSwift
import Foundation
import SIABCore

/// The products the screens name and price, keyed by SKU.
protocol ProductCatalog: AnyObject {
    var products: AnyPublisher<[String: Product], Never> { get }
    var current: [String: Product] { get }
}

/// `store.product` (HQ's catalog, pulled from the box), read only, laid over the seed catalog bundled with the app
/// (`seed-products.json`, a link to `contracts/fixtures/seed/products.json`). The seed covers SKUs the box has not
/// delivered yet: a device paired before its first pull, or a simulator with no box.
final class StoreProductCatalog: ProductCatalog {
    private let database: Database
    private let collection: Collection?
    private let seed: [String: Product]
    private let subject: CurrentValueSubject<[String: Product], Never>
    private var token: ListenerToken?

    var products: AnyPublisher<[String: Product], Never> { subject.eraseToAnyPublisher() }
    var current: [String: Product] { subject.value }

    init(database: Database, seed: [String: Product] = StoreProductCatalog.bundledSeed()) {
        self.database = database
        self.seed = seed
        collection = try? database.collection(name: "product", scope: CustodyStore.storeScope)
        subject = CurrentValueSubject(seed)
        reload()
        token = collection?.addChangeListener(queue: .main) { [weak self] _ in self?.reload() }
    }

    deinit {
        token?.remove()
        // As CustodyStore does: keep the collection alive until notifications already queued on main have run.
        let collection = collection
        DispatchQueue.main.async { _ = collection }
    }

    static func bundledSeed(_ bundle: Bundle = .main) -> [String: Product] {
        guard let url = bundle.url(forResource: "seed-products", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let list = try? JSONDecoder().decode([Product].self, from: data) else { return [:] }
        return Dictionary(list.map { ($0.sku, $0) }) { first, _ in first }
    }

    private func reload() {
        var merged = seed
        for product in stored() { merged[product.sku] = product }
        subject.send(merged)
    }

    /// Every decodable product document; one that does not decode is skipped, as CustodyStore skips them.
    private func stored() -> [Product] {
        guard let collection,
              let query = try? database.createQuery("SELECT META().id AS id FROM `store`.`product`"),
              let rows = try? query.execute().allResults() else { return [] }
        return rows.compactMap { row in
            guard let id = row.string(forKey: "id"), let doc = try? collection.document(id: id),
                  var body = try? JSONSerialization.jsonObject(with: Data(doc.toJSON().utf8)) as? [String: Any]
            else { return nil }
            body["_id"] = id
            guard let data = try? JSONSerialization.data(withJSONObject: body) else { return nil }
            return try? JSONDecoder().decode(Product.self, from: data)
        }
    }
}
