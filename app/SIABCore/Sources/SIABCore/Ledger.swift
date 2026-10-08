import Foundation

// The Swift port of the custody ledger reducer (ports/ledger.md; reference: src/siab_ledger/). The golden fixtures in
// contracts/fixtures/ledger/ are the source of truth; the comments name the rule each step implements.

public enum CustodyState: String, Codable { case held, sold, disputed }

public struct UnitState: Equatable {
    public var sku: String
    public var holder: String?
    public var allocation: String?
    public var state: CustodyState
    public var lastTxn: String?
}

public struct CustodianSKU: Hashable, Comparable {
    public var custodian: String
    public var sku: String
    public init(custodian: String, sku: String) { self.custodian = custodian; self.sku = sku }
    public static func < (a: CustodianSKU, b: CustodianSKU) -> Bool { (a.custodian, a.sku) < (b.custodian, b.sku) }
}

public struct Fork: Equatable {
    public var unitID: String
    public var sku: String
    public var prevTxn: String?
    public var branches: [String]
    public var resolvedBy: String?
}

public struct LedgerState {
    public var units: [String: UnitState]
    public var counts: [CustodianSKU: Int]
    public var allocationCounts: [String: Int]
    /// Sorted by unit, then `prevTxn` (nil first).
    public var forks: [Fork]
    /// Movements a resolution set aside (rule 3).
    public var setAside: Set<String>
    public var store: String
    /// Every transaction in the input, one per id.
    public var transactions: [String: Transaction]
    /// The resolutions that count (status resolved, resolution.by hq), sorted by id.
    public var resolutions: [ExceptionDoc]
    /// Each movement's predecessor (rule 1), when it has one; the id may be absent from `transactions`.
    public var predecessors: [String: String]
    /// Units whose every root is a check_in with prev_txn null.
    public var untraced: Set<String>

    public static func empty(store: String) -> LedgerState {
        LedgerState(units: [:], counts: [:], allocationCounts: [:], forks: [], setAside: [], store: store,
                    transactions: [:], resolutions: [], predecessors: [:], untraced: [])
    }
}

public enum Ledger {
    public static func skuOf(_ unitID: String) -> String {
        String(unitID.split(separator: "#", maxSplits: 1, omittingEmptySubsequences: false)[0])
    }

    /// A check_out or sale with prev_txn null from a custodian other than the store: its writer had no record.
    public static func isBlind(_ t: Transaction, store: String) -> Bool {
        t.prevTxn == nil && t.kind != .checkIn && t.fromCustodian != store
    }

    public static func isStoreRoot(_ t: Transaction, store: String) -> Bool {
        t.prevTxn == nil && t.kind != .checkIn && t.fromCustodian == store
    }

    static func isNullCheckIn(_ t: Transaction) -> Bool { t.kind == .checkIn && t.prevTxn == nil }

    static func order(_ t: Transaction) -> (String, String) { (t.hlc, t.id) }

    /// Rule 5: one document per id. Two different bodies under one id should not happen (documents are immutable);
    /// if they do, the one with the smaller canonical JSON is kept whatever the order, as the reference does.
    static func dedupe<T: Encodable & Identifiable & Hashable>(_ docs: [T]) -> [String: T] where T.ID == String {
        var out: [String: T] = [:]
        for doc in docs {
            guard let kept = out[doc.id] else { out[doc.id] = doc; continue }
            if kept != doc, let a = try? JSONValue(encoding: doc), let b = try? JSONValue(encoding: kept),
               a.canonical < b.canonical {
                out[doc.id] = doc
            }
        }
        return out
    }

    /// Rule 3: only resolutions with status resolved and resolution.by hq count; any other is ignored everywhere.
    public static func hqResolutions(_ docs: [ExceptionDoc]) -> [ExceptionDoc] {
        dedupe(docs).values.filter { $0.status == "resolved" && $0.resolution?.by == Custodian.hq }
            .sorted { $0.id < $1.id }
    }

    /// Rule 1 for the movements of one unit. A blind movement's predecessor is the movement into its from_custodian
    /// with the greatest hlc below its own (set-aside branches included); the bound keeps the forest acyclic.
    static func predecessors(_ movements: [String: Transaction], store: String) -> [String: String] {
        let ordered = movements.values.sorted { order($0) < order($1) }
        var into: [String: [Transaction]] = [:]
        for m in ordered { into[m.toCustodian, default: []].append(m) }
        var out: [String: String] = [:]
        for m in ordered {
            if let prev = m.prevTxn {
                out[m.id] = prev
            } else if isBlind(m, store: store),
                      let below = into[m.fromCustodian]?.last(where: { order($0) < order(m) }) {
                out[m.id] = below.id
            }
        }
        return out
    }

    static func descendants(_ start: [String], _ children: [String: [String]]) -> Set<String> {
        var seen = Set<String>()
        var stack = start
        while let node = stack.popLast() {
            if seen.insert(node).inserted { stack.append(contentsOf: children[node] ?? []) }
        }
        return seen
    }

    struct UnitResult {
        var unit: UnitState
        var forks: [Fork]
        var predecessors: [String: String]
        var untraced: Bool
        var setAside: Set<String>
    }

    static func reduceUnit(_ unitID: String, _ movements: [String: Transaction], store: String,
                           resolutions: [ExceptionDoc]) -> UnitResult {
        let sku = skuOf(unitID)
        let pred = predecessors(movements, store: store)
        var children: [String: [String]] = [:]
        for mid in pred.keys.sorted() { children[pred[mid]!, default: []].append(mid) }

        // Rule 2: siblings under one predecessor id (present or not), and two or more store roots (a root fork).
        var groups: [(prev: String?, branches: [String])] = children.keys.sorted().compactMap { p in
            children[p]!.count >= 2 ? (p, children[p]!) : nil
        }
        let storeRoots = movements.values.filter { isStoreRoot($0, store: store) }.map(\.id).sorted()
        if storeRoots.count >= 2 { groups.insert((nil, storeRoots), at: 0) }

        // Rule 3: a resolution matches the fork with its dispute_key and exactly its branches; the greatest
        // (resolution.hlc, _id) decides; it settles the fork only if it chose a branch, and the other branches and
        // their descendants are set aside. A fork whose branches are all set aside is not reported.
        var setAside = Set<String>()
        var settled: [Fork] = []
        for (prev, branches) in groups {
            let key = "\(unitID)|\(prev ?? "root")"
            let latest = resolutions.filter { $0.disputeKey == key && $0.transactions.sorted() == branches }
                .max { ($0.resolution?.hlc ?? "", $0.id) < ($1.resolution?.hlc ?? "", $1.id) }
            let chosen = latest?.resolution?.chosenTxn
            var resolvedBy: String?
            if let latest, let chosen, branches.contains(chosen) {
                resolvedBy = latest.id
                setAside.formUnion(descendants(branches.filter { $0 != chosen }, children))
            }
            settled.append(Fork(unitID: unitID, sku: sku, prevTxn: prev, branches: branches, resolvedBy: resolvedBy))
        }
        let forks = settled.filter { !$0.branches.allSatisfy(setAside.contains) }

        // Rule 3: an unresolved fork disputes the unit. Rule 4: otherwise the canonical leaf with the greatest hlc.
        let canonical = Set(movements.keys).subtracting(setAside)
        let leaves = canonical.filter { !(children[$0] ?? []).contains(where: canonical.contains) }.map { movements[$0]! }
        let unit: UnitState
        if forks.contains(where: { $0.resolvedBy == nil }) || leaves.isEmpty {
            unit = UnitState(sku: sku, holder: nil, allocation: nil, state: .disputed, lastTxn: nil)
        } else {
            let leaf = leaves.max { order($0) < order($1) }!
            unit = UnitState(sku: sku, holder: leaf.toCustodian, allocation: leaf.toAllocation,
                             state: leaf.kind == .sale ? .sold : .held, lastTxn: leaf.id)
        }

        let roots = movements.values.filter { pred[$0.id].map { movements[$0] == nil } ?? true }
        let untraced = !roots.isEmpty && roots.allSatisfy(isNullCheckIn)
        return UnitResult(unit: unit, forks: forks, predecessors: pred, untraced: untraced, setAside: setAside)
    }

    /// Reduce every transaction this node knows (any order, duplicates allowed by id) and the resolved exceptions.
    /// `store` is the store custodian: a movement with prev_txn null from it is a store root, from anywhere else a
    /// blind movement (rule 1). Pure: no registry, no clock, no I/O.
    public static func reduce(transactions: [Transaction], resolutions: [ExceptionDoc], store: String) -> LedgerState {
        let txns = dedupe(transactions)
        let hq = hqResolutions(resolutions)
        var byUnit: [String: [String: Transaction]] = [:]
        for t in txns.values { byUnit[t.unitID, default: [:]][t.id] = t }

        var state = LedgerState.empty(store: store)
        state.transactions = txns
        state.resolutions = hq
        for unitID in byUnit.keys.sorted() {
            let r = reduceUnit(unitID, byUnit[unitID]!, store: store, resolutions: hq)
            state.units[unitID] = r.unit
            state.forks += r.forks
            state.predecessors.merge(r.predecessors) { a, _ in a }
            state.setAside.formUnion(r.setAside)
            if r.untraced { state.untraced.insert(unitID) }
        }
        for t in txns.values {
            for a in [t.fromAllocation, t.toAllocation].compactMap({ $0 }) { state.allocationCounts[a] = 0 }
        }
        for unit in state.units.values where unit.state == .held {
            state.counts[CustodianSKU(custodian: unit.holder!, sku: unit.sku), default: 0] += 1
            if let a = unit.allocation { state.allocationCounts[a, default: 0] += 1 }
        }
        state.forks.sort { ($0.unitID, $0.prevTxn == nil ? 0 : 1, $0.prevTxn ?? "") < ($1.unitID, $1.prevTxn == nil ? 0 : 1, $1.prevTxn ?? "") }
        return state
    }
}
