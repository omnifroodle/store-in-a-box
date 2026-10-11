import CouchbaseLiteSwift
@testable import SIABCore  // for CustodyStore's write-failure seam, `afterTransactionWrite`
import XCTest
@testable import StoreInABox

/// Against a temporary Couchbase Lite database: the basket over WS4's real `CustodyStore.sell(basket:)` (#114), where
/// the sales commit together and publish once, and a failure inside the batch keeps none of them; and the catalog
/// read from `store.product`.
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
        var published: [Int] = []
        let watch = store.state.dropFirst().sink { published.append($0.transactions.count) }
        defer { watch.cancel() }
        try model.tender(kind: .cash)

        XCTAssertEqual(try savedTransactions(), 2)
        XCTAssertEqual(published, [2], "one state, with the whole basket: the Shelf never sees half of it")
        let sales = store.currentState.transactions.values
        XCTAssertEqual(Set(sales.compactMap(\.basket)).count, 1)
        XCTAssertEqual(store.currentState.units.values.map(\.state), [.sold, .sold])
    }

    /// #119 item 8: the failure is inside the batch, after the first sale was saved, through the Sell screen.
    func testAFailedBasketKeepsNothing() throws {
        let model = SellViewModel(store: store, catalog: FakeCatalog([TestData.rainShell]), scheduler: FakeScheduler())
        model.add(scan: TestData.scan("JKT-RAIN-M-BLU#001"))
        model.add(scan: TestData.scan("JKT-RAIN-M-BLU#002"))
        var saved = 0
        store.afterTransactionWrite = {
            saved += 1
            if saved == 2 { throw Injected() }
        }
        var published: [Int] = []
        let watch = store.state.dropFirst().sink { published.append($0.transactions.count) }
        defer { watch.cancel() }

        XCTAssertThrowsError(try model.tender(kind: .cash))
        XCTAssertEqual(saved, 2, "the first sale was written inside the batch before the failure")
        XCTAssertEqual(try savedTransactions(), 0, "rolled back")
        XCTAssertEqual(published, [], "nothing published for a basket that did not commit")
        XCTAssertTrue(store.currentState.transactions.isEmpty)
        XCTAssertEqual(model.basket.count, 2, "the basket stays for another try")
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
