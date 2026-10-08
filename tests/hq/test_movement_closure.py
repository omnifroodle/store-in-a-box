"""Decision 009 (contracts 0.6.0): a movement exception is keyed and closed by kind and dispute_key, whatever it
attached; a fork at the same movement still binds to its branch set; HQ writes no check_out."""

from __future__ import annotations

import json

from siab_capella.provision import ks
from siab_hq.server import route

TAKE_B = "txn::1792328511000-0000-tablet-b"
SALE = "txn::1792329000000-0000-tablet-a"
KEY = f"JKT-RAIN-M-BLU#001|{SALE}"


def _view(app, status="all"):
    return json.loads(route(app, "GET", f"/api/exceptions?status={status}")[2])


def test_closed_movement_exception_stays_closed_when_its_predecessor_arrives(kit, contracts):
    """closed-foreign-movement-predecessor-arrives: HQ closed tablet-a's foreign sale while tablet-b's take had not
    arrived (its copy attached the sale alone). The take arrives: the movement's exception now attaches both, under a
    new id, but HQ's closure holds by kind and dispute_key. Nothing is written, the entry stays resolved, and a
    tablet's copy that attached the predecessor joins the same entry and closes with it."""
    fx = kit.fixture("closed-foreign-movement-predecessor-arrives")
    hq = kit.hq(fx, drop=(TAKE_B,))
    app = kit.app(hq)
    assert hq.run_once() == []
    (entry,) = _view(app)["disputes"]
    assert (entry["kind"], entry["dispute_key"], entry["status"]) == ("foreign_movement", KEY, "resolved")
    assert [t["_id"] for t in entry["transactions"]] == [SALE]

    kit.put(hq, "transaction", next(t for t in fx["transactions"] if t["_id"] == TAKE_B))
    assert hq.run_once() == []  # 0.5.0 wrote exc::hq::...::74f5bc5e here
    view = _view(app)
    (entry,) = view["disputes"]
    assert (entry["kind"], entry["dispute_key"], entry["status"]) == ("foreign_movement", KEY, "resolved")
    assert [t["_id"] for t in entry["transactions"]] == [TAKE_B, SALE]
    assert [d["_id"] for d in entry["documents"]] == ["exc::hq::JKT-RAIN-M-BLU#001::9390607c"]
    assert entry["resolution"]["note"] == "Customer carried it from tablet-b's table. The sale stands."
    assert view["superseded"] == [] and _view(app, "open")["disputes"] == []

    tablet_copy = {
        "_id": "exc::tablet-a::JKT-RAIN-M-BLU#001::74f5bc5e", "v": 1, "type": "exception",
        "trip": hq.trip, "box": "box-07", "kind": "foreign_movement", "unit_id": "JKT-RAIN-M-BLU#001",
        "sku": "JKT-RAIN-M-BLU", "dispute_key": KEY, "fork_txn": None, "transactions": [TAKE_B, SALE],
        "branches": [{"txn": t["_id"], "device": t["device"], "kind": t["kind"], "to_custodian": t["to_custodian"],
                      "hlc": t["hlc"]} for t in sorted(fx["transactions"], key=lambda t: t["_id"])
                     if t["_id"] in (TAKE_B, SALE)],
        "proposed_resolution": {"action": "review",
                                "note": "Moved by a device that did not hold it. Confirm where the unit is."},
        "status": "open", "resolution": None, "detected_by": "tablet-a",
        "detected_at": "1792329700000-0000-tablet-a"}
    assert contracts.doc_errors("exception", tablet_copy) == []
    kit.put(hq, "exception", tablet_copy)  # replicated up from the box
    assert hq.run_once() == []
    (entry,) = _view(app)["disputes"]
    assert entry["detectors"] == ["hq", "tablet-a"] and entry["status"] == "resolved"

    status, _, body = route(app, "POST", "/api/exceptions/resolve", json.dumps({
        "dispute_key": KEY, "transactions": [TAKE_B, SALE], "chosen_txn": None, "note": "Still stands."}).encode())
    assert (status, json.loads(body)["updated"]) == (200, 2)  # every copy of that kind and key, whatever it attached
    docs = kit.exceptions(hq)
    assert {d["resolution"]["note"] for d in docs.values()} == {"Still stands."}
    for d in docs.values():
        assert contracts.doc_errors("exception", d) == []


def test_closed_movement_does_not_hide_a_fork_at_the_same_key(kit):
    """closed-foreign-movement-fork-at-same-key: the fork at the flagged take shares its dispute_key. The queue keeps
    them apart by kind, the reconciler writes the fork, and resolving the fork touches only the fork's copies."""
    fx = kit.fixture("closed-foreign-movement-fork-at-same-key")
    hq = kit.hq(fx)
    (written,) = hq.run_once()
    assert written["kind"] == "oversell" and written["_id"] == "exc::hq::JKT-RAIN-M-BLU#001::80e2d0fd"
    app = kit.app(hq)
    (fork,) = _view(app, "open")["disputes"]
    (flagged,) = _view(app, "resolved")["disputes"]
    assert fork["dispute_key"] == flagged["dispute_key"]
    assert (fork["kind"], flagged["kind"]) == ("oversell", "foreign_movement")
    assert [d["_id"] for d in fork["documents"]] == [written["_id"]]
    assert [d["_id"] for d in flagged["documents"]] == ["exc::hq::JKT-RAIN-M-BLU#001::e8302267"]

    branches = [t["_id"] for t in fork["transactions"]]
    status, _, body = route(app, "POST", "/api/exceptions/resolve", json.dumps({
        "dispute_key": fork["dispute_key"], "transactions": branches, "chosen_txn": branches[0],
        "note": "phone-1 has it."}).encode())
    assert (status, json.loads(body)["updated"]) == (200, 1)
    assert kit.exceptions(hq)["exc::hq::JKT-RAIN-M-BLU#001::e8302267"]["resolution"]["note"] == (
        "tablet-b has it. The take stands.")


def test_hq_detects_a_foreign_hq_check_out_and_writes_none(kit, contracts):
    """foreign-hq-check-out: hq has no box, so an hq pack is foreign; the reconciler flags it. HQ itself only ever
    writes sales (the staged oversell) and exception documents."""
    fx = kit.fixture("foreign-hq-check-out")
    hq = kit.hq(fx)
    written = hq.run_once()
    expected = fx["expected"]["exceptions"]["docs"]
    assert [{k: v for k, v in d.items() if k != "detected_at"} for d in written] == expected
    assert all(contracts.doc_errors("exception", d) == [] for d in written)
    assert {c[1] for c in hq.gw.calls if c[0] == "upsert"} == {ks("exception")}
