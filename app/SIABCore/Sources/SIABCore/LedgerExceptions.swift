import CryptoKit
import Foundation

// Rules 6, 7 and 8: the exception documents a detector writes (reference: src/siab_ledger/exceptions.py).

extension Ledger {
    static let proposedResolution: [ExceptionKind: ExceptionDoc.ProposedResolution] = [
        .oversell: .init(action: "refund", note: "Sold twice. Refund one sale, then choose the branch that stands."),
        .doubleScan: .init(action: "review",
                           note: "Scanned out twice. Choose the movement that matches where the unit is."),
        .unexpectedCheckIn: .init(action: "review",
                                  note: "Checked in by a device that did not hold it. Confirm where the unit is."),
        .foreignMovement: .init(action: "review",
                                note: "Moved by a device that did not hold it. Confirm where the unit is."),
    ]

    /// First 8 hex characters of sha256 over the ids, sorted and joined by '|'.
    public static func hash8(_ txnIDs: [String]) -> String {
        let digest = SHA256.hash(data: Data(txnIDs.sorted().joined(separator: "|").utf8))
        return digest.prefix(4).map { byte in
            let hex = String(byte, radix: 16)
            return hex.count == 1 ? "0" + hex : hex
        }.joined()
    }

    public static func exceptionID(detector: String, unitID: String, txnIDs: [String]) -> String {
        "exc::\(detector)::\(unitID)::\(hash8(txnIDs))"
    }

    /// Rule 6: a check_in from neither its writer nor its box, or with no record of the unit (prev_txn null).
    public static func isUnexpectedCheckIn(_ t: Transaction) -> Bool {
        t.kind == .checkIn && (t.prevTxn == nil || (t.fromCustodian != t.device && t.fromCustodian != t.box))
    }

    /// Rule 8: the custodians a writer acts for: itself, its box, and the store when it is hq.
    public static func actsFor(_ t: Transaction, store: String) -> Set<String> {
        var out: Set<String> = [t.device]
        if let box = t.box { out.insert(box) }
        if t.device == Custodian.hq { out.insert(store) }
        return out
    }

    /// Rule 8: a check_out onto, or a sale from, a custodian the writer does not act for.
    public static func isForeign(_ t: Transaction, store: String) -> Bool {
        switch t.kind {
        case .checkOut: return !actsFor(t, store: store).contains(t.toCustodian)
        case .sale: return !actsFor(t, store: store).contains(t.fromCustodian)
        case .checkIn: return false
        }
    }

    static func document(_ state: LedgerState, detector: String, trip: String, box: String?, kind: ExceptionKind,
                         unitID: String, disputeKey: String, forkTxn: String?, txnIDs: [String],
                         detectedAt: String?) -> ExceptionDoc {
        let ids = txnIDs.sorted()
        let branches = ids.map { id -> ExceptionDoc.Branch in
            let t = state.transactions[id]!
            return .init(txn: id, device: t.device, kind: t.kind, toCustodian: t.toCustodian, hlc: t.hlc)
        }
        return ExceptionDoc(
            id: exceptionID(detector: detector, unitID: unitID, txnIDs: ids), trip: trip,
            box: detector == Custodian.hq ? nil : box, kind: kind, unitID: unitID, sku: state.units[unitID]!.sku,
            disputeKey: disputeKey, forkTxn: forkTxn, transactions: ids, branches: branches,
            proposedResolution: proposedResolution[kind]!, status: "open", resolution: nil, detectedBy: detector,
            detectedAt: detectedAt)
    }

    /// The exception documents `detector` must write for `state`, sorted by id: one per unresolved fork, one per
    /// unexpected check-in and one per foreign movement, leaving out set-aside movements and any whose dispute_key
    /// and transactions match a resolution that counts. `detectedAt` (the detector's hlc) is set only when given, so
    /// the same state always gives the same documents.
    public static func exceptions(for state: LedgerState, detector: String, trip: String, box: String?,
                                  detectedAt: String? = nil) -> [ExceptionDoc] {
        var docs: [String: ExceptionDoc] = [:]
        for fork in state.forks where fork.resolvedBy == nil {
            let latest = fork.branches.map { state.transactions[$0]! }.max { order($0) < order($1) }!
            let doc = document(state, detector: detector, trip: trip, box: box,
                               kind: latest.kind == .sale ? .oversell : .doubleScan, unitID: fork.unitID,
                               disputeKey: "\(fork.unitID)|\(fork.prevTxn ?? "root")", forkTxn: fork.prevTxn,
                               txnIDs: fork.branches, detectedAt: detectedAt)
            docs[doc.id] = doc
        }
        for tid in state.transactions.keys.sorted() where !state.setAside.contains(tid) {
            let t = state.transactions[tid]!
            let kind: ExceptionKind
            if isUnexpectedCheckIn(t) { kind = .unexpectedCheckIn }
            else if isForeign(t, store: state.store) { kind = .foreignMovement }
            else { continue }
            var ids = [tid]
            if let prev = t.prevTxn, state.transactions[prev] != nil { ids.append(prev) }
            let doc = document(state, detector: detector, trip: trip, box: box, kind: kind, unitID: t.unitID,
                               disputeKey: "\(t.unitID)|\(tid)", forkTxn: nil, txnIDs: ids, detectedAt: detectedAt)
            docs[doc.id] = doc
        }
        // Rule 7 (0.6.0): a fork's exception is closed by a counting resolution with its dispute_key and exactly its
        // transactions; an unexpected check-in's or a foreign movement's by one of the same kind and dispute_key,
        // whatever transactions it attached (the key names the movement HQ judged).
        let settled = Set(state.resolutions.map { "\($0.disputeKey)\n\($0.transactions.sorted().joined(separator: ","))" })
        let movementKinds: Set<ExceptionKind> = [.unexpectedCheckIn, .foreignMovement]
        let closed = Set(state.resolutions.filter { movementKinds.contains($0.kind) }.map { "\($0.kind)\n\($0.disputeKey)" })
        return docs.keys.sorted().map { docs[$0]! }.filter { doc in
            movementKinds.contains(doc.kind)
                ? !closed.contains("\(doc.kind)\n\(doc.disputeKey)")
                : !settled.contains("\(doc.disputeKey)\n\(doc.transactions.joined(separator: ","))")
        }
    }
}
