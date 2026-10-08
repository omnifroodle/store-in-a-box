"""HQ's queue is the reducer's, not the documents' (decision 008, #77 finding F)."""

from __future__ import annotations

import json

from siab_hq.reconcile import AWAITING, WITHDRAWN, queue
from siab_hq.server import route

RETURN = "txn::1792328650000-0000-tablet-a"


def _get(app, path):
    status, _, body = route(app, "GET", path)
    assert status == 200, body
    return json.loads(body) if path.startswith("/api/") else body.decode()


def test_queue_follows_reducer_not_documents(kit):
    """null-root-take-after-return before the return arrives: tablet-b's blind take continues the pack, a fork with
    tablet-a's take, and HQ writes it. The return arrives; the blind take now continues the return; the fork is gone.
    HQ's open document stays as written, but it is listed as superseded, not as a dispute."""
    fx = kit.fixture("null-root-take-after-return")
    hq = kit.hq(fx, drop=(RETURN,))
    (written,) = hq.run_once()
    assert written["kind"] == "double_scan"
    app = kit.app(hq)
    assert [e["dispute_key"] for e in _get(app, "/api/exceptions")["disputes"]] == [written["dispute_key"]]

    kit.put(hq, "transaction", next(t for t in fx["transactions"] if t["_id"] == RETURN))
    assert hq.run_once() == []
    view = _get(app, "/api/exceptions?status=all")
    assert view["disputes"] == []
    assert [d["_id"] for d in view["superseded"]] == [written["_id"]]
    assert kit.exceptions(hq)[written["_id"]]["status"] == "open"
    assert "superseded (1)" in _get(app, "/panels/exceptions")
    assert hq.status.forks_open == 0

    status, _, body = route(app, "POST", "/api/exceptions/close-superseded", b"{}")
    assert (status, json.loads(body)) == (200, {"updated": 1})
    closed = kit.exceptions(hq)[written["_id"]]
    assert closed["status"] == "resolved"
    assert closed["resolution"]["chosen_txn"] is None and closed["resolution"]["note"] == "superseded"
    assert _get(app, "/api/exceptions?status=all") == {"disputes": [], "superseded": []}
    assert hq.snapshot().state.units["JKT-RAIN-M-BLU#005"].holder == "tablet-b"


def test_withdrawn_choice_is_back_on_queue(kit, clock, contracts):
    """latest-resolution-chooses-nothing: both copies are resolved, the latest with nothing chosen. The fork is open
    by the reducer, so the dispute is on the queue (no new document is written) and reads 'withdrawn: choose again';
    HQ's next choice, stamped after both earlier decisions though its wall clock is behind, settles it."""
    clock.ms = 1792328400000
    hq = kit.hq(kit.fixture("latest-resolution-chooses-nothing"), clock)
    assert hq.run_once() == []
    app = kit.app(hq)
    (entry,) = _get(app, "/api/exceptions")["disputes"]
    assert entry["label"] == WITHDRAWN and entry["status"] == "open"
    assert entry["detectors"] == ["hq", "tablet-a"]
    assert [d["status"] for d in entry["documents"]] == ["resolved", "resolved"]
    assert WITHDRAWN in _get(app, "/panels/exceptions")

    reply = hq.resolve(hq.trip, entry["dispute_key"], [t["_id"] for t in entry["transactions"]],
                       "txn::1792328511000-0000-tablet-b", "tablet-b has it after all.")
    assert reply == {"updated": 2, "hlc": "1792330500000-0001-hq"}
    state = hq.snapshot().state
    assert state.forks[0].resolved_by == "exc::tablet-a::JKT-RAIN-M-BLU#001::111c7a4e"  # the _id tie-break
    assert state.units["JKT-RAIN-M-BLU#001"].holder == "tablet-b"
    assert _get(app, "/api/exceptions")["disputes"] == []
    (settled,) = _get(app, "/api/exceptions?status=resolved")["disputes"]
    assert settled["resolution"]["chosen_txn"] == "txn::1792328511000-0000-tablet-b"
    for doc in kit.exceptions(hq).values():
        assert contracts.doc_errors("exception", doc) == []


def test_a_live_dispute_without_a_document_waits_for_hqs_copy(kit):
    fx = kit.fixture("oversell-hq")
    hq = kit.hq(fx)
    data, state = hq._read(hq.trip)
    (entry,) = queue(state, data.exceptions)["disputes"]
    assert entry["label"] == AWAITING and entry["documents"] == [] and entry["detectors"] == []


def test_branch_leaf_is_the_branchs_last_movement(kit):
    """In the staged oversell the pack branch's leaf is the tablet's sale (#61)."""
    hq = kit.hq(kit.fixture("oversell-hq"))
    (entry,) = _get(kit.app(hq), "/api/exceptions")["disputes"]
    assert entry["kind"] == "oversell" and entry["dispute_key"] == "JKT-RAIN-M-BLU#001|root"
    leaves = {b["txn"]["_id"]: b["leaf"]["_id"] for b in entry["branches"]}
    assert leaves == {"txn::1792328410000-0000-tablet-a": "txn::1792329000000-0000-tablet-a",
                      "txn::1792329100000-0000-hq": "txn::1792329100000-0000-hq"}
    panel = _get(kit.app(hq), "/panels/exceptions")
    assert "leaf: tablet-a sale box-07 &rarr; customer" in panel
    assert panel.count('data-action="resolve"') == 2


def test_foreign_movement_renders_like_an_unexpected_check_in(kit):
    for name, kind in (("foreign-sale", "foreign_movement"), ("unexpected-check-in", "unexpected_check_in")):
        hq = kit.hq(kit.fixture(name))
        (entry,) = _get(kit.app(hq), "/api/exceptions")["disputes"]
        assert entry["kind"] == kind and len(entry["transactions"]) == 2
        panel = _get(kit.app(hq), "/panels/exceptions")
        assert "did not hold it" in panel and "before it:" in panel
        assert 'data-chosen=""' in panel  # closed, with nothing to choose


def test_status_filters_by_the_entrys_state(kit):
    hq = kit.hq(kit.fixture("resolved-fork"))
    app = kit.app(hq)
    assert _get(app, "/api/exceptions?status=open")["disputes"] == []
    (entry,) = _get(app, "/api/exceptions?status=resolved")["disputes"]
    assert entry["status"] == "resolved" and entry["resolution"]["chosen_txn"] == "txn::1792328510000-0000-tablet-a"
    assert len(_get(app, "/api/exceptions?status=all")["disputes"]) == 1
    assert route(app, "GET", "/api/exceptions?status=closed")[0] == 400


def test_closed_unexpected_check_in_is_resolved_not_open(kit):
    hq = kit.hq(kit.fixture("unexpected-check-in"))
    hq.run_once()
    (entry,) = _get(kit.app(hq), "/api/exceptions")["disputes"]
    hq.resolve(hq.trip, entry["dispute_key"], [t["_id"] for t in entry["transactions"]], None, "box has it")
    assert _get(kit.app(hq), "/api/exceptions")["disputes"] == []
    (closed,) = _get(kit.app(hq), "/api/exceptions?status=resolved")["disputes"]
    assert closed["dispute_key"] == entry["dispute_key"] and closed["resolution"]["note"] == "box has it"
    assert hq.run_once() == []
