"""``exceptions_for``: the exception documents a detector writes, rules 6 and 7 of ``contracts/fixtures/README.md``."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

from .chain import LedgerState

OVERSELL, DOUBLE_SCAN, UNEXPECTED_CHECK_IN = "oversell", "double_scan", "unexpected_check_in"
FOREIGN = "foreign_movement"

PROPOSED_RESOLUTION = {
    OVERSELL: {"action": "refund", "note": "Sold twice. Refund one sale, then choose the branch that stands."},
    DOUBLE_SCAN: {"action": "review",
                  "note": "Scanned out twice. Choose the movement that matches where the unit is."},
    UNEXPECTED_CHECK_IN: {"action": "review",
                          "note": "Checked in by a device that did not hold it. Confirm where the unit is."},
    FOREIGN: {"action": "review", "note": "Moved by a device that did not hold it. Confirm where the unit is."},
}


def hash8(txn_ids: Iterable[str]) -> str:
    """First 8 hex characters of sha256 over the ids, sorted and joined by '|'."""
    return hashlib.sha256("|".join(sorted(txn_ids)).encode()).hexdigest()[:8]


def exception_id(detector: str, unit_id: str, txn_ids: Iterable[str]) -> str:
    return f"exc::{detector}::{unit_id}::{hash8(txn_ids)}"


def is_unexpected_check_in(txn: Mapping) -> bool:
    """Rule 6: a check_in from neither its writer nor its box, or with no record of the unit (prev_txn null)."""
    if txn["kind"] != "check_in":
        return False
    return txn["prev_txn"] is None or txn["from_custodian"] not in (txn["device"], txn["box"])


def acts_for(txn: Mapping, store: str) -> set:
    """Rule 8: the custodians a writer acts for: itself, its box, and the store when it is hq."""
    out = {txn["device"]}
    if txn["box"] is not None:
        out.add(txn["box"])
    if txn["device"] == "hq":
        out.add(store)
    return out


def is_foreign(txn: Mapping, store: str) -> bool:
    """Rule 8: a check_out onto, or a sale from, a custodian the writer does not act for."""
    if txn["kind"] == "check_out":
        return txn["to_custodian"] not in acts_for(txn, store)
    if txn["kind"] == "sale":
        return txn["from_custodian"] not in acts_for(txn, store)
    return False


def _branch(txn: Mapping) -> dict:
    return {"txn": txn["_id"], "device": txn["device"], "kind": txn["kind"], "to_custodian": txn["to_custodian"],
            "hlc": txn["hlc"]}


def _document(state: LedgerState, *, detector: str, trip: str, box: str | None, kind: str, unit_id: str,
              dispute_key: str, fork_txn: str | None, txn_ids: Iterable[str], detected_at: str | None) -> dict:
    ids = sorted(txn_ids)
    doc = {
        "_id": exception_id(detector, unit_id, ids),
        "v": 1,
        "type": "exception",
        "trip": trip,
        "box": None if detector == "hq" else box,
        "kind": kind,
        "unit_id": unit_id,
        "sku": state.units[unit_id].sku,
        "dispute_key": dispute_key,
        "fork_txn": fork_txn,
        "transactions": ids,
        "branches": [_branch(state.transactions[i]) for i in ids],
        "proposed_resolution": dict(PROPOSED_RESOLUTION[kind]),
        "status": "open",
        "resolution": None,
        "detected_by": detector,
    }
    if detected_at is not None:
        doc["detected_at"] = detected_at
    return doc


def exceptions_for(state: LedgerState, detector: str, trip: str, box: str | None, *,
                   detected_at: str | None = None) -> list[dict]:
    """The exception documents ``detector`` must write for ``state``, sorted by ``_id``.

    One per unresolved fork and one per unexpected check-in, leaving out any whose ``dispute_key`` and
    ``transactions`` match a resolution that counts. Each carries its ``_id``; ``detected_at`` (the detector's hlc)
    is added only when given, so the same state always gives byte-identical documents.
    """
    docs: dict[str, dict] = {}
    for fork in state.forks:
        if fork.resolved_by is not None:
            continue
        latest = max((state.transactions[b] for b in fork.branches), key=lambda t: (t["hlc"], t["_id"]))
        kind = OVERSELL if latest["kind"] == "sale" else DOUBLE_SCAN
        doc = _document(state, detector=detector, trip=trip, box=box, kind=kind, unit_id=fork.unit_id,
                        dispute_key=f"{fork.unit_id}|{fork.prev_txn or 'root'}", fork_txn=fork.prev_txn,
                        txn_ids=fork.branches, detected_at=detected_at)
        docs[doc["_id"]] = doc
    for tid in sorted(state.transactions):
        txn = state.transactions[tid]
        if tid in state.set_aside:
            continue  # rule 3: set-aside movements raise nothing
        if is_unexpected_check_in(txn):
            kind = UNEXPECTED_CHECK_IN
        elif is_foreign(txn, state.store):
            kind = FOREIGN
        else:
            continue
        ids = [tid] + ([txn["prev_txn"]] if txn["prev_txn"] in state.transactions else [])
        doc = _document(state, detector=detector, trip=trip, box=box, kind=kind,
                        unit_id=txn["unit_id"], dispute_key=f"{txn['unit_id']}|{tid}", fork_txn=None, txn_ids=ids,
                        detected_at=detected_at)
        docs[doc["_id"]] = doc
    settled = {(r.get("dispute_key"), tuple(sorted(r.get("transactions") or ()))) for r in state.resolutions}
    closed = {(r.get("kind"), r.get("dispute_key")) for r in state.resolutions
              if r.get("kind") in (UNEXPECTED_CHECK_IN, FOREIGN)}

    def is_closed(doc):
        if doc["kind"] in (UNEXPECTED_CHECK_IN, FOREIGN):
            return (doc["kind"], doc["dispute_key"]) in closed
        return (doc["dispute_key"], tuple(doc["transactions"])) in settled

    return [docs[i] for i in sorted(docs) if not is_closed(docs[i])]
