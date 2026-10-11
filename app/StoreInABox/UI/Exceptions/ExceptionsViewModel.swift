import Combine
import Foundation
import SIABCore

/// One open dispute: the transactions involved, side by side.
struct DisputeRow: Identifiable, Equatable {
    struct Side: Identifiable, Equatable {
        enum Role: Equatable { case branch, flagged, before }
        /// The transaction id.
        let id: String
        let role: Role
        let device: String
        let kind: MovementKind
        let from: String
        let to: String
        let hlc: String
        let prev: String?
    }

    /// The dispute key, and whether this is a fork or a flagged movement (a fork at a flagged movement has the same
    /// key, decision 009).
    var id: String { (isFork ? "fork|" : "movement|") + disputeKey }
    let disputeKey: String
    let unit: UnitID
    let kind: ExceptionKind
    let isFork: Bool
    let sides: [Side]

    var title: String {
        switch kind {
        case .oversell: return "Sold twice"
        case .doubleScan: return "Scanned out twice"
        case .unexpectedCheckIn: return "Unexpected check-in"
        case .foreignMovement: return "Foreign movement"
        }
    }

    /// For a flagged movement: who moved a unit the record says it did not hold.
    var note: String? {
        guard !isFork, let flagged = sides.first(where: { $0.role == .flagged }) else { return nil }
        let context = sides.contains { $0.role == .before } ? ""
            : flagged.prev == nil ? " (no earlier record of the unit)"
            : " (the movement before it has not reached this device)"
        return "\(flagged.device) did not hold it" + context
    }
}

/// Exceptions: the open disputes in this device's ledger state, read only (HQ resolves). They are what this
/// device's detector reports for the current state (`Ledger.exceptions`), so a dispute HQ has closed is gone as soon
/// as its resolution arrives.
@MainActor
final class ExceptionsViewModel: ObservableObject {
    @Published private(set) var disputes: [DisputeRow] = []
    private var subscription: AnyCancellable?

    init(store: CustodyStoring) {
        let identity = store.identity
        subscription = store.state.sink { [weak self] state in
            let rows = Self.disputes(state: state, identity: identity)
            if rows != self?.disputes { self?.disputes = rows }
        }
    }

    static func disputes(state: LedgerState, identity: DeviceIdentity) -> [DisputeRow] {
        let docs = Ledger.exceptions(for: state, detector: identity.device, trip: identity.trip, box: identity.box)
        let movementKinds: Set<ExceptionKind> = [.unexpectedCheckIn, .foreignMovement]
        let groups = Dictionary(grouping: docs) { doc in
            (movementKinds.contains(doc.kind) ? "movement|" : "fork|") + doc.disputeKey
        }
        return groups.keys.sorted().map { key in
            let group = groups[key]!
            let first = group[0]
            let isFork = !movementKinds.contains(first.kind)
            let flagged = isFork ? nil : first.disputeKey.split(separator: "|", maxSplits: 1).last.map(String.init)
            let ids = Set(group.flatMap(\.transactions))
            let sides = ids.compactMap { state.transactions[$0] }.sorted { $0.hlc < $1.hlc }.map { t in
                DisputeRow.Side(id: t.id, role: isFork ? .branch : (t.id == flagged ? .flagged : .before),
                                device: t.device, kind: t.kind, from: t.fromCustodian, to: t.toCustodian, hlc: t.hlc,
                                prev: t.prevTxn)
            }
            return DisputeRow(disputeKey: first.disputeKey, unit: first.unitID, kind: first.kind, isFork: isFork,
                              sides: sides)
        }
    }
}
