import Foundation
import SIABCore

enum CustodyMode: String, CaseIterable, Identifiable {
    /// Check out from the box onto this device.
    case take
    /// Check in to the parent (the box, in Phase 0).
    case return_
    /// Check out from the store onto the box, this device acting for the box.
    case pack

    var id: String { rawValue }
    var title: String {
        switch self {
        case .take: "Take"
        case .return_: "Return"
        case .pack: "Pack"
        }
    }
}

struct CustodyLine: Identifiable, Equatable {
    /// The transaction written.
    let id: String
    let unit: UnitID
    let sku: String
    let mode: CustodyMode
    /// The allocation the movement fills (take, pack) or empties (return); nil when it has none.
    let allocation: String?
    /// Whose allocation that is: the receiving custodian, or for a return the one giving the unit back.
    let allocationHolder: String
    /// The record had the unit somewhere else, or had no record of it. The movement stands; the ledger flags it.
    let disagrees: Bool
}

/// Custody: take, return or pack, one unit per scan, with a running list of this session's scans.
@MainActor
final class CustodyViewModel: ObservableObject {
    @Published var mode: CustodyMode = .take
    @Published private(set) var session: [CustodyLine] = []
    private let store: CustodyStoring

    init(store: CustodyStoring) {
        self.store = store
    }

    /// "TAKING FROM box-07", "RETURNING TO box-07" or "PACKING store-richmond → box-07".
    var header: String {
        let id = store.identity
        switch mode {
        case .take: return "TAKING FROM \(id.box)"
        case .return_: return "RETURNING TO \(id.box)"
        case .pack: return "PACKING \(id.store) → \(id.box)"
        }
    }

    /// Writes the movement for the current mode. Never refuses because of what the record says: a unit the record
    /// places elsewhere, or does not know, is moved and its line tagged. Throws only when the write fails.
    func apply(scan: ScanResult) throws {
        let id = store.identity
        let disagrees = recordDisagrees(scan.unit, identity: id)
        let txn: Transaction
        switch mode {
        case .take: txn = try store.checkOut(unit: scan.unit, from: id.box, to: id.device, actingFor: nil)
        case .return_: txn = try store.checkIn(unit: scan.unit)
        case .pack: txn = try store.checkOut(unit: scan.unit, from: id.store, to: id.box, actingFor: id.box)
        }
        let empties = mode == .return_
        session.insert(CustodyLine(id: txn.id, unit: scan.unit, sku: scan.sku, mode: mode,
                                   allocation: empties ? txn.fromAllocation : txn.toAllocation,
                                   allocationHolder: empties ? txn.fromCustodian : txn.toCustodian,
                                   disagrees: disagrees), at: 0)
    }

    /// For the scanner: `apply`, with the words to show.
    func handle(scan: ScanResult) -> Result<String, ScanRejection> {
        do {
            try apply(scan: scan)
            return .success("\(mode.title): \(scan.unit)")
        } catch {
            return .failure(.notRecorded(String(describing: error)))
        }
    }

    func clearSession() { session = [] }

    /// Take expects the box to hold the unit; return expects this device to; pack expects the store to, or no
    /// record at all (the first scan out of the store).
    private func recordDisagrees(_ unit: UnitID, identity: DeviceIdentity) -> Bool {
        let state = store.currentState
        switch mode {
        case .take: return !RecordCheck.holds(unit, by: [identity.box], state: state)
        case .return_: return !RecordCheck.holds(unit, by: [identity.device], state: state)
        case .pack: return state.units[unit] != nil && !RecordCheck.holds(unit, by: [identity.store], state: state)
        }
    }
}
