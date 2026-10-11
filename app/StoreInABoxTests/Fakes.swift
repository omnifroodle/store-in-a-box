import Combine
import Foundation
import SIABCore
@testable import StoreInABox

enum TestData {
    static let trip = "trip-2026-10-18-riverfest"
    static let tabletA = DeviceIdentity(device: "tablet-a", box: "box-07", trip: trip)

    /// A product as HQ seeds it.
    static func product(_ sku: String, name: String, cents: Int) -> Product {
        let json = """
        {"_id": "product::\(sku)", "v": 1, "type": "product", "sku": "\(sku)", "name": "\(name)",
         "price": {"cents": \(cents), "currency": "USD"}, "category": "jackets", "category_family": "outerwear",
         "size": null, "color": null, "tags": [], "regions": ["va-central"]}
        """
        return try! JSONDecoder().decode(Product.self, from: Data(json.utf8))
    }

    static let rainShell = product("JKT-RAIN-M-BLU", name: "Rain shell", cents: 12900)
    static let beanie = product("HAT-BEANIE-OS", name: "Beanie", cents: 2450)

    static func scan(_ payload: String) -> ScanResult { try! ScanParser.parse(payload).get() }
}

final class FakeCatalog: ProductCatalog {
    let subject: CurrentValueSubject<[String: Product], Never>
    init(_ products: [Product]) { subject = CurrentValueSubject(Dictionary(uniqueKeysWithValues: products.map { ($0.sku, $0) })) }
    var products: AnyPublisher<[String: Product], Never> { subject.eraseToAnyPublisher() }
    var current: [String: Product] { subject.value }
}

/// Virtual time for the confirmation banner.
final class FakeScheduler: Scheduling {
    var now: TimeInterval = 0
    private var pending: [(at: TimeInterval, work: @MainActor () -> Void)] = []

    func after(_ seconds: TimeInterval, _ work: @escaping @MainActor () -> Void) { pending.append((now + seconds, work)) }

    @MainActor
    func advance(_ seconds: TimeInterval) {
        now += seconds
        let due = pending.filter { $0.at <= now }
        pending.removeAll { $0.at <= now }
        due.forEach { $0.work() }
    }
}

struct SilentFeedback: ScanFeedback {
    func accepted() {}
    func rejected() {}
}

/// `CustodyStore`'s write semantics, simplified, over the real reducer: each write is a transaction from what this
/// fake's ledger knows of the unit; the state is `Ledger.reduce` over everything written or "pulled". A batch
/// publishes once at the end, and a batch that throws keeps none of its writes.
final class FakeCustodyStore: CustodyStoring {
    enum Failure: Error { case injected }
    struct Call: Equatable { var name: String; var unit: String; var from: String?; var to: String?; var actingFor: String? }

    let identity: DeviceIdentity
    private let subject: CurrentValueSubject<LedgerState, Never>
    private(set) var written: [Transaction] = []
    private(set) var calls: [Call] = []
    private(set) var batches = 0
    private var pulled: [Transaction] = []
    private var pending: [Transaction]?
    private var ms: Int64 = 1_792_328_400_000
    /// Make the next `sell` throw.
    var failNextSell = false

    init(identity: DeviceIdentity = TestData.tabletA) {
        self.identity = identity
        subject = CurrentValueSubject(.empty(store: identity.store))
    }

    var state: AnyPublisher<LedgerState, Never> { subject.eraseToAnyPublisher() }
    var currentState: LedgerState { subject.value }

    /// A movement another device wrote, as if replication had pulled it.
    @discardableResult
    func pull(_ kind: MovementKind, _ unit: String, from: String, to: String, device: String,
              prev: String? = nil) -> Transaction {
        let txn = make(kind, unit, from: from, to: to, prev: prev, device: device)
        pulled.append(txn)
        publish()
        return txn
    }

    func checkOut(unit: String, from: String, to: String, actingFor box: String?) throws -> Transaction {
        calls.append(Call(name: "checkOut", unit: unit, from: from, to: to, actingFor: box))
        let known = currentState.units[unit]
        return record(make(.checkOut, unit, from: from, to: to, prev: known?.lastTxn, device: identity.device,
                           toAllocation: "alloc::\(stamp())"))
    }

    func checkIn(unit: String) throws -> Transaction {
        calls.append(Call(name: "checkIn", unit: unit))
        let known = currentState.units[unit]
        return record(make(.checkIn, unit, from: known?.holder ?? Custodian.unknown, to: identity.box,
                           prev: known?.lastTxn, device: identity.device, fromAllocation: known?.allocation))
    }

    func sell(unit: String, tender: Tender, price: Money, basket: String?) throws -> Transaction {
        calls.append(Call(name: "sell", unit: unit))
        if failNextSell { failNextSell = false; throw Failure.injected }
        let known = currentState.units[unit]
        var txn = make(.sale, unit, from: known?.holder ?? identity.box, to: Custodian.customer, prev: known?.lastTxn,
                       device: identity.device, fromAllocation: known?.allocation)
        txn.basket = basket
        txn.price = price
        txn.tender = tender
        return record(txn)
    }

    func inBatch(_ work: () throws -> Void) throws {
        batches += 1
        pending = []
        defer { pending = nil }
        try work()
        written += pending ?? []
        publish()
    }

    private func record(_ txn: Transaction) -> Transaction {
        if pending != nil { pending!.append(txn) } else { written.append(txn); publish() }
        return txn
    }

    /// An exception document HQ resolved, as if pulled.
    func pull(resolution: ExceptionDoc) {
        resolutions.append(resolution)
        publish()
    }

    private var resolutions: [ExceptionDoc] = []

    private func publish() {
        subject.send(Ledger.reduce(transactions: pulled + written, resolutions: resolutions, store: identity.store))
    }

    private func stamp() -> String {
        ms += 1000
        return HLC(ms: ms, counter: 0, device: identity.device).string
    }

    private func make(_ kind: MovementKind, _ unit: String, from: String, to: String, prev: String?, device: String,
                      fromAllocation: String? = nil, toAllocation: String? = nil) -> Transaction {
        ms += 1000
        let hlc = HLC(ms: ms, counter: 0, device: device).string
        return Transaction(id: "txn::" + hlc, trip: identity.trip, box: identity.box, kind: kind, unitID: unit,
                           sku: Ledger.skuOf(unit), fromCustodian: from, toCustodian: to, prevTxn: prev,
                           fromAllocation: fromAllocation, toAllocation: toAllocation, device: device, hlc: hlc,
                           deviceClock: "2026-10-18T14:00:00Z")
    }
}
