"""The Capella-side reconciler and HQ's writes: exceptions as detector ``hq``, resolutions, the staged oversell.

The cloud adjudicates nothing: the reconciler reads the trip's transactions and exceptions, runs WS1's reducer
(``siab_ledger``, imported, never re-implemented) and writes the exception documents ``exceptions_for`` gives for
detector ``hq`` that do not exist yet. Writes are idempotent by id. HQ's queue is the reducer's (decisions 008 and
009): one entry per dispute the reducer knows, whatever documents exist.

HQ keeps one hybrid logical clock for device ``hq``. Its ``last`` is the greater of the last HLC it issued and the
greatest it has read (every ``resolution.hlc`` of the trip's exceptions, and every transaction and detection), so it
is monotonic across restarts without a file. ``resolution.at`` is a label in UTC, whole seconds, ``Z``.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from siab_capella.gateway import CapellaGateway
from siab_capella.provision import ks
from siab_ledger import LedgerState, compare_hlc, exceptions_for, hlc_now, parse_hlc, reduce
from siab_ledger.exceptions import is_foreign, is_unexpected_check_in

from . import queries
from .queries import TripData

HQ = "hq"
FORK_KINDS = ("oversell", "double_scan")
MOVEMENT_KINDS = ("unexpected_check_in", "foreign_movement")
SUPERSEDED_NOTE = "superseded"
WITHDRAWN = "withdrawn: choose again"
AWAITING = "open: HQ's copy on the next run"

Clock = Callable[[], int]  # unix milliseconds


class BadRequest(ValueError):
    """The request names something HQ will not write (HTTP 400)."""


class NotFound(LookupError):
    """Nothing matches the request (HTTP 404)."""


def iso(ms: int) -> str:
    """RFC 3339 in UTC, whole seconds, ``Z`` (decision 006)."""
    return datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class HqClock:
    """One HLC for device ``hq``: ``hlc_now(clock, last, "hq")`` with ``last`` the greatest HLC issued or read."""

    def __init__(self, clock: Clock):
        self.clock = clock
        self.last: str | None = None

    def observe(self, hlc: str | None) -> None:
        if hlc and (self.last is None or compare_hlc(hlc, self.last) > 0):
            self.last = hlc

    def observe_trip(self, data: TripData) -> None:
        """Every ``resolution.hlc`` among the trip's exceptions (the blueprint's rule), and every transaction's and
        detection's HLC: what HQ writes next comes after everything it has seen, as an HLC receive would have it, so
        the staged sale is the later branch even when the laptop's clock is behind the tablets'."""
        for e in data.exceptions:
            if isinstance(e.get("resolution"), dict):
                self.observe(e["resolution"].get("hlc"))
            self.observe(e.get("detected_at"))
        for t in data.transactions:
            self.observe(t.get("hlc"))

    def now(self) -> str:
        self.last = hlc_now(self.clock, self.last, HQ)
        return self.last

    def at(self) -> str:
        return iso(self.clock())


@dataclass(frozen=True)
class Snapshot:
    data: TripData
    state: LedgerState
    as_of: str


@dataclass
class Status:
    last_run: str | None = None
    exceptions_written: int = 0
    forks_open: int = 0
    last_error: str | None = None

    def to_json(self) -> dict:
        return {"last_run": self.last_run, "exceptions_written": self.exceptions_written,
                "forks_open": self.forks_open, "last_error": self.last_error}


# ---------------------------------------------------------------- the queue (pure)

def entry_key(doc: dict) -> tuple:
    """Which queue entry a document (or a resolution) belongs to (decisions 006 and 009): a fork's by its
    ``dispute_key`` and exact branch set, an unexpected check-in's or a foreign movement's by its ``kind`` and
    ``dispute_key`` (the movement), whatever transactions it attached."""
    if doc.get("kind") in FORK_KINDS:
        return ("fork", doc.get("dispute_key"), tuple(sorted(doc.get("transactions") or ())))
    return (doc.get("kind"), doc.get("dispute_key"))


def _children(state: LedgerState) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for tid, pred in sorted(state.predecessors.items()):
        if pred is not None:
            out[pred].append(tid)
    return out


def leaf(state: LedgerState, txn_id: str, children: dict[str, list[str]]) -> dict:
    """The last movement of the branch that starts at ``txn_id``: its canonical descendant with no canonical
    successor, the greatest ``hlc`` when there are several."""
    seen: set[str] = set()
    stack = [txn_id]
    while stack:
        node = stack.pop()
        if node in seen or node in state.set_aside or node not in state.transactions:
            continue
        seen.add(node)
        stack.extend(children.get(node, ()))
    ends = [state.transactions[t] for t in seen if not any(c in seen for c in children.get(t, ()))]
    if not ends:
        return state.transactions[txn_id]
    return max(ends, key=lambda t: (t["hlc"], t["_id"]))


def _fork_kind(state: LedgerState, branches: Iterable[str]) -> str:
    latest = max((state.transactions[b] for b in branches), key=lambda t: (t["hlc"], t["_id"]))
    return "oversell" if latest["kind"] == "sale" else "double_scan"


def _latest(resolutions: Iterable[dict]) -> dict | None:
    return max(resolutions, key=lambda r: (r["resolution"].get("hlc") or "", r["_id"]), default=None)


def disputes(state: LedgerState) -> dict[tuple, dict]:
    """Every dispute the reducer knows, by ``entry_key``: each fork in ``forks`` (open while ``resolved_by`` is null),
    and each unexpected check-in (rule 6) or foreign movement (rule 8) not set aside, open until a counting
    resolution of the same ``kind`` and ``dispute_key`` closes it (decision 009)."""
    counting: dict[tuple, list[dict]] = defaultdict(list)
    for r in state.resolutions:
        counting[entry_key(r)].append(r)
    by_id = {r["_id"]: r for r in state.resolutions}
    out: dict[tuple, dict] = {}
    for fork in state.forks:
        key = ("fork", f"{fork.unit_id}|{fork.prev_txn or 'root'}", tuple(fork.branches))
        open_ = fork.resolved_by is None
        out[key] = {"kind": _fork_kind(state, fork.branches), "unit_id": fork.unit_id, "dispute_key": key[1],
                    "transactions": list(fork.branches), "status": "open" if open_ else "resolved",
                    "deciding": None if open_ else by_id.get(fork.resolved_by),
                    "withdrawn": open_ and key in counting}
    for tid in sorted(state.transactions):
        txn = state.transactions[tid]
        if tid in state.set_aside:
            continue
        if is_unexpected_check_in(txn):
            kind = "unexpected_check_in"
        elif is_foreign(txn, state.store):
            kind = "foreign_movement"
        else:
            continue
        key = (kind, f"{txn['unit_id']}|{tid}")
        deciding = _latest(counting.get(key, ()))
        attached = [tid] + ([txn["prev_txn"]] if txn["prev_txn"] in state.transactions else [])
        out[key] = {"kind": kind, "unit_id": txn["unit_id"], "dispute_key": key[1], "transactions": sorted(attached),
                    "status": "open" if deciding is None else "resolved", "deciding": deciding, "withdrawn": False}
    return out


def queue(state: LedgerState, exceptions: list[dict], status: str = "open") -> dict:
    """``GET /api/exceptions``: the reducer's disputes, filtered by the entry's status (``open``, ``resolved``,
    ``all``), and the open documents that belong to none of them (``superseded``)."""
    docs_by: dict[tuple, list[dict]] = defaultdict(list)
    for e in exceptions:
        docs_by[entry_key(e)].append(e)
    children = _children(state)
    known = disputes(state)
    entries = []
    for key, d in known.items():
        if status != "all" and d["status"] != status:
            continue
        docs = sorted(docs_by.get(key, []), key=lambda e: e["_id"])
        if d["status"] == "resolved":
            label = "resolved"
        else:
            label = WITHDRAWN if d["withdrawn"] else ("open" if docs else AWAITING)
        entries.append({
            "dispute_key": d["dispute_key"],
            "kind": d["kind"],
            "unit_id": d["unit_id"],
            "sku": state.units[d["unit_id"]].sku,
            "detectors": sorted({e["detected_by"] for e in docs}),
            "transactions": [state.transactions[t] for t in d["transactions"]],
            "branches": [{"txn": state.transactions[t], "leaf": leaf(state, t, children)} for t in d["transactions"]],
            "documents": docs,
            "status": d["status"],
            "label": label,
            "resolution": d["deciding"]["resolution"] if d["deciding"] else None,
        })
    entries.sort(key=lambda e: (e["status"] != "open", e["unit_id"], e["dispute_key"], e["kind"]))
    superseded = sorted((e for e in exceptions if e.get("status") == "open" and entry_key(e) not in known),
                        key=lambda e: e["_id"])
    return {"disputes": entries, "superseded": superseded}


def stageable(state: LedgerState, trip_doc: dict) -> list[dict]:
    """Units the ledger shows as held by the box or one of the trip's devices: what the staged oversell may sell."""
    holders = {trip_doc.get("box"), *trip_doc.get("devices", ())}
    return [{"unit_id": uid, "sku": u.sku, "holder": u.holder} for uid, u in sorted(state.units.items())
            if u.state == "held" and u.holder in holders]


# ---------------------------------------------------------------- the reconciler and HQ's writes

@dataclass
class Hq:
    """The reconciler, HQ's clock and HQ's writes, over one ``CapellaGateway``. ``trip`` is the trip the reconciler
    watches; reads of another trip are computed on demand and write nothing."""

    gw: CapellaGateway
    trip: str
    clock: Clock
    new_basket: Callable[[], str] = field(default=lambda: str(uuid.uuid4()))
    hlc: HqClock = field(init=False)
    status: Status = field(default_factory=Status)
    _snapshot: Snapshot | None = field(default=None, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def __post_init__(self) -> None:
        self.hlc = HqClock(self.clock)

    def _read(self, trip: str) -> tuple[TripData, LedgerState]:
        data = queries.load(self.gw, trip)
        self.hlc.observe_trip(data)
        return data, reduce(data.transactions, data.exceptions, store=data.store)

    def run_once(self, trip: str | None = None, *, dry_run: bool = False) -> list[dict]:
        """One reconcile: the exception documents to write for detector ``hq`` (those whose id does not exist yet).
        Written unless ``dry_run``; the result is cached for the API when ``trip`` is the watched trip."""
        trip = trip or self.trip
        with self._lock:
            data, state = self._read(trip)
            existing = {e["_id"] for e in data.exceptions}
            planned = [d for d in exceptions_for(state, HQ, trip, None) if d["_id"] not in existing]
            if planned and not dry_run:
                detected_at = self.hlc.now()
                planned = [{**d, "detected_at": detected_at} for d in planned]
                for doc in planned:
                    self.gw.upsert(ks("exception"), doc["_id"], queries.body(doc))
                data = replace(data, exceptions=data.exceptions + planned)
            if trip == self.trip and not dry_run:
                self._snapshot = Snapshot(data, state, iso(self.clock()))
                self.status = Status(last_run=iso(self.clock()),
                                     exceptions_written=self.status.exceptions_written + len(planned),
                                     forks_open=sum(1 for f in state.forks if f.resolved_by is None))
            return planned

    def snapshot(self, trip: str | None = None) -> Snapshot:
        """The watched trip's last reconcile (running one if there is none), or a fresh read of another trip."""
        trip = trip or self.trip
        with self._lock:
            if trip == self.trip:
                if self._snapshot is None:
                    self.run_once()
                assert self._snapshot is not None
                return self._snapshot
            data, state = self._read(trip)
            return Snapshot(data, state, iso(self.clock()))

    async def run_every(self, interval_s: float, *, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                        ticks: int | None = None) -> None:
        """Reconcile every ``interval_s`` (``ticks`` times, or forever). ``sleep`` is injected: tests pass a virtual
        one. A failed run is recorded in ``status.last_error`` and the loop goes on."""
        n = 0
        while ticks is None or n < ticks:
            await sleep(interval_s)
            n += 1
            try:
                await asyncio.to_thread(self.run_once)
            except Exception as e:  # noqa: BLE001 (the loop must outlive a dropped connection)
                self.status.last_error = f"{type(e).__name__}: {e}"

    def _resolution(self, chosen_txn: str | None, note: str) -> dict:
        return {"by": HQ, "hlc": self.hlc.now(), "at": self.hlc.at(), "chosen_txn": chosen_txn, "note": note}

    def _write_resolved(self, docs: list[dict], resolution: dict) -> None:
        for doc in docs:
            self.gw.upsert(ks("exception"), doc["_id"],
                           {**queries.body(doc), "status": "resolved", "resolution": dict(resolution)})

    def resolve(self, trip: str, dispute_key: str, transactions: list[str], chosen_txn: str | None,
                note: str = "") -> dict:
        """Resolve every detector's copy of one dispute.

        A fork's copies are those written for exactly ``transactions`` (decision 006: copies for another branch set
        stay as they are), and it needs ``chosen_txn`` among them. An unexpected check-in's or a foreign movement's
        copies are every one of that kind with that ``dispute_key``, whatever they attached (decision 009), and it
        closes with ``chosen_txn`` null. The request is about the movement when ``transactions`` holds the movement
        its ``dispute_key`` names (a fork's branches never hold their predecessor), else about the fork."""
        if not isinstance(dispute_key, str) or not dispute_key:
            raise BadRequest("dispute_key is required")
        if (not isinstance(transactions, list) or not transactions
                or not all(isinstance(t, str) for t in transactions)):
            raise BadRequest("transactions must be the non-empty list of transaction ids HQ chose from")
        if chosen_txn is not None and not isinstance(chosen_txn, str):
            raise BadRequest("chosen_txn must be a transaction id or null")
        if not isinstance(note, str):
            raise BadRequest("note must be a string")
        fork = dispute_key.partition("|")[2] not in transactions
        want = ("fork", dispute_key, tuple(sorted(transactions)))

        def copies(exceptions: list[dict]) -> list[dict]:
            if fork:
                return [e for e in exceptions if entry_key(e) == want]
            return [e for e in exceptions if e.get("kind") in MOVEMENT_KINDS and e.get("dispute_key") == dispute_key]

        with self._lock:
            data, _ = self._read(trip)
            docs = copies(data.exceptions)
            if not docs:  # a live dispute with no document yet gets HQ's own first
                self.run_once(trip)
                data, _ = self._read(trip)
                docs = copies(data.exceptions)
            if not docs:
                raise NotFound(f"no exception of {trip} has dispute_key {dispute_key} and those transactions")
            if fork and chosen_txn not in want[2]:
                raise BadRequest("a fork is resolved by choosing one of its transactions")
            if not fork and chosen_txn is not None:
                raise BadRequest(f"{docs[0]['kind']} closes with chosen_txn null")
            resolution = self._resolution(chosen_txn, note)
            self._write_resolved(docs, resolution)
            self.run_once(trip)
            return {"updated": len(docs), "hlc": resolution["hlc"]}

    def close_superseded(self, trip: str) -> dict:
        """Close every open document that belongs to no dispute the reducer knows, with ``chosen_txn`` null and note
        ``superseded``. Such a document matches no fork and no flagged movement, so closing it settles, closes and
        withdraws nothing."""
        with self._lock:
            data, state = self._read(trip)
            docs = queue(state, data.exceptions, "all")["superseded"]
            if docs:
                self._write_resolved(docs, self._resolution(None, SUPERSEDED_NOTE))
                self.run_once(trip)
            return {"updated": len(docs)}

    def stage_hq_sale(self, trip: str, unit_id: str, price: dict | None = None) -> dict:
        """The staged oversell: HQ sells, from the store, a unit the ledger shows on the box or a tablet."""
        with self._lock:
            data, state = self._read(trip)
            offered = {u["unit_id"]: u for u in stageable(state, data.trip_doc)}
            if unit_id not in offered:
                raise BadRequest(f"{unit_id} is not held by the box or a tablet of {trip}")
            sku = offered[unit_id]["sku"]
            if price is None:
                product = self.gw.get(ks("product"), f"product::{sku}")
                price = (product or {}).get("price")
                if price is None:
                    raise BadRequest(f"product::{sku} has no price; send one")
            if (not isinstance(price, dict) or set(price) != {"cents", "currency"} or price["currency"] != "USD"
                    or not isinstance(price["cents"], int) or isinstance(price["cents"], bool) or price["cents"] < 0):
                raise BadRequest('price is {"cents": <integer >= 0>, "currency": "USD"} (decision 003)')
            hlc = self.hlc.now()
            assert parse_hlc(hlc).device == HQ
            txn = {
                "v": 1, "type": "transaction", "trip": trip, "box": None, "kind": "sale", "unit_id": unit_id,
                "sku": sku, "from_custodian": data.store, "to_custodian": "customer", "prev_txn": None,
                "from_allocation": None, "to_allocation": None, "device": HQ, "hlc": hlc,
                "device_clock": self.hlc.at(), "box_clock": None, "basket": self.new_basket(),
                "price": dict(price), "tender": {"kind": "card_simulated", "amount": dict(price)},
            }
            txn_id = f"txn::{hlc}"
            self.gw.upsert(ks("transaction"), txn_id, txn)
            self.run_once(trip)
            return {"id": txn_id}
