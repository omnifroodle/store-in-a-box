import Combine
import Foundation
import SIABCore

/// A unit's id: its QR payload `<SKU>#<serial>`.
typealias UnitID = String

/// What the screens use of WS4's `CustodyStore`. The view models depend on this protocol only, so their tests fake it.
protocol CustodyStoring: AnyObject {
    var identity: DeviceIdentity { get }
    var state: AnyPublisher<LedgerState, Never> { get }
    var currentState: LedgerState { get }
    @discardableResult
    func checkOut(unit: String, from: String, to: String, actingFor box: String?) throws -> Transaction
    @discardableResult
    func checkIn(unit: String) throws -> Transaction
    @discardableResult
    func sell(unit: String, tender: Tender, price: Money, basket: String?) throws -> Transaction
    /// Runs `work` as one batch: every write inside it commits together, or none of them does.
    func inBatch(_ work: () throws -> Void) throws
}

extension CustodyStore: CustodyStoring {
    /// `CustodyStore` has no basket call yet (#114), so this wraps its per-unit writes in an outer
    /// `Database.inBatch`. Couchbase Lite nests batches, so the inner ones commit only with the outer one. If the
    /// outer batch fails, the store has already published states that include the rolled-back writes, so this
    /// rebuilds from what was actually saved.
    func inBatch(_ work: () throws -> Void) throws {
        do {
            try database.inBatch(using: work)
        } catch {
            _ = try? rebuild()
            throw error
        }
    }
}

/// Runs work later on the main actor. Tests use a fake with virtual time.
protocol Scheduling {
    func after(_ seconds: TimeInterval, _ work: @escaping @MainActor () -> Void)
}

struct MainQueueScheduler: Scheduling {
    func after(_ seconds: TimeInterval, _ work: @escaping @MainActor () -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { MainActor.assumeIsolated { work() } }
    }
}

/// Whether the record agrees with a scan. A scan the record disagrees with is still accepted: the movement stands,
/// the ledger flags it (rule 6 or rule 8), and the screen shows the amber "record disagrees" tag.
enum RecordCheck {
    /// A sale from this device or its box, of a unit the record has held by one of them.
    static func saleDisagrees(_ unit: UnitID, state: LedgerState, identity: DeviceIdentity) -> Bool {
        !holds(unit, by: [identity.device, identity.box], state: state)
    }

    static func holds(_ unit: UnitID, by holders: Set<String>, state: LedgerState) -> Bool {
        guard let record = state.units[unit], record.state == .held, let holder = record.holder else { return false }
        return holders.contains(holder)
    }
}
