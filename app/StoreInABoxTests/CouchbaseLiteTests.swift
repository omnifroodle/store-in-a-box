import CouchbaseLiteSwift
import SIABCore
import XCTest
@testable import StoreInABox

/// Against a temporary Couchbase Lite database: the basket batch over WS4's real `CustodyStore` (#114), where the
/// sales commit together and a failure part-way keeps none of them, and the catalog read from `store.product`.
@MainActor
final class CouchbaseLiteTests: XCTestCase {
    struct Clock: SIABCore.Clock { func nowMs() -> Int64 { 1_792_328_400_000 } }
    struct Injected: Error {}

    var directory: URL!
    var database: Database!
    var store: CustodyStore!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        var config = DatabaseConfiguration()
        config.directory = directory.path
        database = try Database(name: "batch", config: config)
        store = try CustodyStore(database: database, identity: TestData.tabletA, clock: Clock())
    }

    override func tearDownWithError() throws {
        store = nil
        let drained = expectation(description: "main queue drained")
        DispatchQueue.main.async { drained.fulfill() }
        wait(for: [drained], timeout: 10)
        try database.close()
        try Database.delete(withName: "batch", inDirectory: directory.path)
        try? FileManager.default.removeItem(at: directory)
    }

    private func savedTransactions() throws -> Int {
        let query = try database.createQuery("SELECT COUNT(*) AS n FROM `store`.`transaction`")
        return try query.execute().allResults().first?.int(forKey: "n") ?? -1
    }

    func testTheBasketCommitsAsOneBatch() throws {
        let model = SellViewModel(store: store, catalog: FakeCatalog([TestData.rainShell]), scheduler: FakeScheduler())
        model.add(scan: TestData.scan("JKT-RAIN-M-BLU#001"))
        model.add(scan: TestData.scan("JKT-RAIN-M-BLU#002"))
        try model.tender(kind: .cash)

        XCTAssertEqual(try savedTransactions(), 2)
        let sales = store.currentState.transactions.values
        XCTAssertEqual(Set(sales.compactMap(\.basket)).count, 1)
        XCTAssertEqual(store.currentState.units.values.map(\.state), [.sold, .sold])
    }

    func testAFailedBasketKeepsNothing() throws {
        let tender = Tender(kind: .cash, amount: Money(cents: 25800))
        XCTAssertThrowsError(try store.inBatch {
            try store.sell(unit: "JKT-RAIN-M-BLU#001", tender: tender, price: Money(cents: 12900), basket: nil)
            throw Injected()
        })
        XCTAssertEqual(try savedTransactions(), 0, "rolled back")
        XCTAssertTrue(store.currentState.transactions.isEmpty, "the published state was rebuilt from what was saved")
    }

    /// The seed bundled with the app, with `store.product` laid over it as documents arrive.
    func testTheCatalogLaysStoreProductsOverTheSeed() throws {
        let seed = StoreProductCatalog.bundledSeed()
        XCTAssertEqual(seed.count, 16, "contracts/fixtures/seed/products.json")
        XCTAssertEqual(seed["JKT-RAIN-M-BLU"]?.price, Money(cents: 12900))

        let catalog = StoreProductCatalog(database: database, seed: seed)
        XCTAssertEqual(catalog.current.count, 16)
        let changed = expectation(description: "catalog follows store.product")
        let watch = catalog.products.dropFirst().sink { if $0["JKT-RAIN-M-BLU"]?.price.cents == 9900 { changed.fulfill() } }
        let collection = try XCTUnwrap(database.collection(name: "product", scope: "store"))
        let json = """
        {"v": 1, "type": "product", "sku": "JKT-RAIN-M-BLU", "name": "Rain shell (sale)",
         "price": {"cents": 9900, "currency": "USD"}, "category": "jackets", "category_family": "outerwear",
         "size": "M", "color": "blue", "tags": [], "regions": ["va-central"]}
        """
        try collection.save(document: MutableDocument(id: "product::JKT-RAIN-M-BLU", json: json))
        wait(for: [changed], timeout: 5)
        watch.cancel()
        XCTAssertEqual(catalog.current["JKT-RAIN-M-BLU"]?.name, "Rain shell (sale)")
        XCTAssertEqual(catalog.current.count, 16)
    }
}
