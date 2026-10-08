"""``reduce``: the custody ledger reducer, rules 1 to 5 of ``contracts/fixtures/README.md`` (and ``ports/ledger.md``).

Pure functions over ``transaction`` and resolved ``exception`` documents (dicts shaped by the contracts' schemas,
with their ``_id``). No I/O: the caller reads the documents and writes what the detector emits.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

HELD, SOLD, DISPUTED = "held", "sold", "disputed"


@dataclass(frozen=True)
class Unit:
    sku: str
    holder: str | None
    allocation: str | None
    state: str
    last_txn: str | None

    def to_json(self) -> dict:
        return {"sku": self.sku, "holder": self.holder, "allocation": self.allocation, "state": self.state,
                "last_txn": self.last_txn}


@dataclass(frozen=True)
class Fork:
    unit_id: str
    sku: str
    prev_txn: str | None
    branches: tuple[str, ...]
    resolved_by: str | None

    def to_json(self) -> dict:
        return {"unit_id": self.unit_id, "sku": self.sku, "prev_txn": self.prev_txn, "branches": list(self.branches),
                "resolved_by": self.resolved_by}


@dataclass(frozen=True)
class LedgerState:
    """What ``reduce`` derives. The first four fields are the interface; the rest feed ``exceptions_for`` and
    ``conservation`` and let tests inspect the forest."""

    units: Mapping[str, Unit]
    counts: Mapping[tuple[str, str], int]
    allocation_counts: Mapping[str, int]
    forks: tuple[Fork, ...]
    store: str
    transactions: Mapping[str, dict]
    """Every transaction in the input, one per id, by id."""
    resolutions: tuple[dict, ...]
    """The resolutions that count (status resolved, resolution.by hq), sorted by id."""
    predecessors: Mapping[str, str | None]
    """Each transaction's predecessor (rule 1): the id its prev_txn names, the implied one for a blind movement, or
    None. The id may be absent from ``transactions`` (a dangling root)."""
    untraced: frozenset[str]
    """Units whose every root is a check_in with prev_txn null."""

    def to_json(self) -> dict:
        """``units``, ``counts``, ``allocation_counts`` and ``forks`` in the fixtures' shape and order."""
        return {
            "units": {uid: self.units[uid].to_json() for uid in sorted(self.units)},
            "counts": [{"custodian": c, "sku": s, "qty": q} for (c, s), q in sorted(self.counts.items()) if q >= 1],
            "allocation_counts": {a: self.allocation_counts[a] for a in sorted(self.allocation_counts)},
            "forks": [f.to_json() for f in self.forks],
        }


def sku_of(unit_id: str) -> str:
    return unit_id.split("#", 1)[0]


def is_blind(txn: Mapping, store: str) -> bool:
    """A check_out or sale with prev_txn null from a custodian other than the store: its writer had no record."""
    return txn["prev_txn"] is None and txn["kind"] in ("check_out", "sale") and txn["from_custodian"] != store


def is_store_root(txn: Mapping, store: str) -> bool:
    return txn["prev_txn"] is None and txn["kind"] != "check_in" and txn["from_custodian"] == store


def is_null_check_in(txn: Mapping) -> bool:
    return txn["kind"] == "check_in" and txn["prev_txn"] is None


def _order(txn: Mapping) -> tuple[str, str]:
    return (txn["hlc"], txn["_id"])


def _canonical_json(doc: Mapping) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"))


def _dedupe(docs: Iterable[Mapping]) -> dict[str, dict]:
    """One document per id. Two different bodies under one id should not happen (documents are immutable); if they
    do, the same one is kept whatever the order, so the result stays a function of the set."""
    out: dict[str, dict] = {}
    for doc in docs:
        doc_id = doc["_id"]
        if doc_id not in out or _canonical_json(doc) < _canonical_json(out[doc_id]):
            out[doc_id] = dict(doc)
    return out


def hq_resolutions(resolutions: Iterable[Mapping]) -> tuple[dict, ...]:
    """The resolutions that count (rule 3): status resolved and resolution.by hq. Any other is ignored."""
    kept = [
        doc for doc in _dedupe(resolutions).values()
        if doc.get("status") == "resolved" and isinstance(doc.get("resolution"), Mapping)
        and doc["resolution"].get("by") == "hq"
    ]
    return tuple(sorted(kept, key=lambda d: d["_id"]))


def predecessors(movements: Mapping[str, Mapping], store: str) -> dict[str, str | None]:
    """Rule 1 for the movements of one unit: each movement's predecessor id, or None.

    A blind movement's predecessor is the movement into its from_custodian with the greatest hlc below its own, among
    every movement given (set-aside branches included); the hlc bound keeps the forest acyclic.
    """
    ordered = sorted(movements.values(), key=_order)
    into: dict[str, list[Mapping]] = defaultdict(list)
    for m in ordered:
        into[m["to_custodian"]].append(m)
    out: dict[str, str | None] = {}
    for m in ordered:
        if m["prev_txn"] is not None:
            out[m["_id"]] = m["prev_txn"]
        elif is_blind(m, store):
            below = [u for u in into[m["from_custodian"]] if _order(u) < _order(m)]
            out[m["_id"]] = below[-1]["_id"] if below else None
        else:
            out[m["_id"]] = None
    return out


def _descendants(start: Iterable[str], children: Mapping[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(start)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(children.get(node, ()))
    return seen


def _reduce_unit(unit_id: str, movements: Mapping[str, Mapping], store: str, resolutions: tuple[dict, ...]):
    sku = sku_of(unit_id)
    pred = predecessors(movements, store)
    children: dict[str, list[str]] = defaultdict(list)
    for mid in sorted(pred):
        if pred[mid] is not None:
            children[pred[mid]].append(mid)

    # Rule 2: siblings under one predecessor id (present or not), and two or more store roots.
    groups: list[tuple[str | None, list[str]]] = [(p, kids) for p, kids in sorted(children.items()) if len(kids) >= 2]
    store_roots = sorted(mid for mid, m in movements.items() if is_store_root(m, store))
    if len(store_roots) >= 2:
        groups.insert(0, (None, store_roots))

    # Rule 3 (0.4.0): a resolution matches the fork with its dispute_key and exactly its transactions; among several
    # matches the greatest (resolution.at, _id) decides, and it settles the fork only if it chose one of the branches.
    # The other branches and their descendants are set aside, and a fork whose branches are all set aside (one
    # inside a set-aside branch) is not reported. Every settled fork's set-aside subtree is computed first: a
    # settled fork nested inside another's set-aside subtree only sets aside movements already set aside.
    settled: list[tuple[str | None, list[str], str | None]] = []
    ignored: set[str] = set()
    for prev, branches in groups:
        key = f"{unit_id}|{prev or 'root'}"
        matching = [r for r in resolutions
                    if r.get("dispute_key") == key and sorted(r.get("transactions") or ()) == branches]
        latest = max(matching, key=lambda r: (r["resolution"].get("at") or "", r["_id"]), default=None)
        chosen = latest["resolution"].get("chosen_txn") if latest else None
        resolved_by = latest["_id"] if chosen in branches else None
        if resolved_by is not None:
            ignored |= _descendants((b for b in branches if b != chosen), children)
        settled.append((prev, branches, resolved_by))
    forks = [Fork(unit_id, sku, prev, tuple(branches), resolved_by) for prev, branches, resolved_by in settled
             if not all(b in ignored for b in branches)]

    # Rule 3: an unresolved fork disputes the unit. Rule 4: otherwise the canonical leaf with the greatest hlc.
    canonical = {mid for mid in movements if mid not in ignored}
    leaves = [movements[mid] for mid in canonical if not any(c in canonical for c in children.get(mid, ()))]
    if any(f.resolved_by is None for f in forks) or not leaves:
        unit = Unit(sku, None, None, DISPUTED, None)
    else:
        leaf = max(leaves, key=_order)
        state = SOLD if leaf["kind"] == "sale" else HELD
        unit = Unit(sku, leaf["to_custodian"], leaf["to_allocation"], state, leaf["_id"])

    roots = [m for mid, m in movements.items() if pred[mid] is None or pred[mid] not in movements]
    untraced = bool(roots) and all(is_null_check_in(m) for m in roots)
    return unit, forks, pred, untraced


def reduce(transactions: Iterable[Mapping], resolutions: Iterable[Mapping] = (), *, store: str) -> LedgerState:
    """Reduce every transaction this node knows (any order, duplicates allowed by id) and the resolved exceptions.

    ``store`` is the store custodian (``store-richmond`` in Phase 0): a movement with prev_txn null from it is a store
    root, and from anywhere else a blind movement (rule 1).
    """
    txns = _dedupe(transactions)
    hq = hq_resolutions(resolutions)
    by_unit: dict[str, dict[str, dict]] = defaultdict(dict)
    for tid, t in txns.items():
        by_unit[t["unit_id"]][tid] = t

    units: dict[str, Unit] = {}
    forks: list[Fork] = []
    preds: dict[str, str | None] = {}
    untraced: set[str] = set()
    for unit_id in sorted(by_unit):
        unit, unit_forks, unit_preds, is_untraced = _reduce_unit(unit_id, by_unit[unit_id], store, hq)
        units[unit_id] = unit
        forks.extend(unit_forks)
        preds.update(unit_preds)
        if is_untraced:
            untraced.add(unit_id)

    counts: dict[tuple[str, str], int] = defaultdict(int)
    allocation_counts: dict[str, int] = {}
    for t in txns.values():
        for alloc in (t["from_allocation"], t["to_allocation"]):
            if alloc is not None:
                allocation_counts[alloc] = 0
    for unit in units.values():
        if unit.state == HELD:
            counts[(unit.holder, unit.sku)] += 1
            if unit.allocation is not None:
                allocation_counts[unit.allocation] = allocation_counts.get(unit.allocation, 0) + 1

    forks.sort(key=lambda f: (f.unit_id, f.prev_txn is not None, f.prev_txn or ""))
    return LedgerState(
        units=units,
        counts=dict(counts),
        allocation_counts=allocation_counts,
        forks=tuple(forks),
        store=store,
        transactions=txns,
        resolutions=hq,
        predecessors=preds,
        untraced=frozenset(untraced),
    )
