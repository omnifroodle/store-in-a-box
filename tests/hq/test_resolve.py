"""POST /api/exceptions/resolve: binds to the branch set HQ chose from, updates every detector's copy of it."""

from __future__ import annotations

import json

from siab_hq.server import route

PACK = "txn::1792328410000-0000-tablet-a"
TAKE_A, TAKE_B = "txn::1792328510000-0000-tablet-a", "txn::1792328511000-0000-tablet-b"
TAKE_PHONE = "txn::1792331000000-0000-phone-1"


def _post(app, path, body):
    status, _, reply = route(app, "POST", path, json.dumps(body).encode())
    return status, json.loads(reply)


def _detector_copy(fx: dict, detected_at: str) -> dict:
    """The fixture's expected document, as the detector that wrote it stored it."""
    (doc,) = fx["expected"]["exceptions"]["docs"]
    return {**doc, "detected_at": detected_at}


def test_resolve_updates_every_detectors_copy(kit, contracts):
    fx = kit.fixture("oversell-hq")
    hq = kit.hq(fx)
    kit.put(hq, "exception", _detector_copy(fx, "1792329200000-0000-tablet-a"))
    (hq_copy,) = hq.run_once()
    sale = "txn::1792329100000-0000-hq"
    status, reply = _post(kit.app(hq), "/api/exceptions/resolve", {
        "trip": hq.trip, "dispute_key": "JKT-RAIN-M-BLU#001|root", "transactions": [sale, PACK],
        "chosen_txn": PACK, "note": "Refunded the flagship sale; the venue's stands."})
    assert status == 200
    assert reply == {"updated": 2, "hlc": "1792340000000-0001-hq"}
    docs = kit.exceptions(hq)
    assert set(docs) == {hq_copy["_id"], "exc::tablet-a::JKT-RAIN-M-BLU#001::57cf515b"}
    for doc in docs.values():
        assert doc["status"] == "resolved"
        assert doc["resolution"] == {"by": "hq", "hlc": "1792340000000-0001-hq", "at": "2026-10-18T16:13:20Z",
                                     "chosen_txn": PACK, "note": "Refunded the flagship sale; the venue's stands."}
        assert list(doc["resolution"]) == ["by", "hlc", "at", "chosen_txn", "note"]
        assert contracts.doc_errors("exception", doc) == []
    state = hq.snapshot().state
    assert state.forks[0].resolved_by is not None
    assert state.units["JKT-RAIN-M-BLU#001"].state == "sold"  # the tablet's sale is the leaf of the chosen branch


def test_resolve_updates_only_the_matching_branch_set(kit):
    """third-branch-at-resolved-fork, plus HQ's open copy of the two-branch set: resolving the three-branch set
    touches only the copy written for it (decision 006); the two-branch copies stay as they are."""
    fx = kit.fixture("third-branch-at-resolved-fork")
    hq = kit.hq(fx)
    two = {**fx["resolutions"][0], "_id": "exc::hq::JKT-RAIN-M-BLU#001::111c7a4e", "box": None,
           "detected_by": "hq", "detected_at": "1792328600000-0000-hq", "status": "open", "resolution": None}
    kit.put(hq, "exception", two)
    before = kit.exceptions(hq)
    (three,) = hq.run_once()
    assert three["transactions"] == [TAKE_A, TAKE_B, TAKE_PHONE]
    status, reply = _post(kit.app(hq), "/api/exceptions/resolve", {
        "dispute_key": three["dispute_key"], "transactions": [TAKE_PHONE, TAKE_A, TAKE_B],
        "chosen_txn": TAKE_PHONE, "note": "phone-1 has it."})
    assert (status, reply["updated"]) == (200, 1)
    after = kit.exceptions(hq)
    assert after[three["_id"]]["resolution"]["chosen_txn"] == TAKE_PHONE
    for doc_id, doc in before.items():
        assert after[doc_id] == doc, doc_id
    assert hq.snapshot().state.units["JKT-RAIN-M-BLU#001"].holder == "phone-1"
    assert [d["_id"] for d in hq.snapshot() and route_superseded(kit, hq)] == [two["_id"]]


def route_superseded(kit, hq):
    return json.loads(route(kit.app(hq), "GET", "/api/exceptions?status=all")[2])["superseded"]


def test_resolve_rejects_a_choice_outside_the_branches(kit):
    hq = kit.hq(kit.fixture("double-scan"))
    hq.run_once()
    app = kit.app(hq)
    base = {"dispute_key": f"JKT-RAIN-M-BLU#001|{PACK}", "transactions": [TAKE_A, TAKE_B], "note": ""}
    writes = len(hq.gw.calls)
    for chosen in (PACK, None, "txn::1792399999999-0000-tablet-a"):
        status, reply = _post(app, "/api/exceptions/resolve", {**base, "chosen_txn": chosen})
        assert status == 400, chosen
        assert "choosing one of its transactions" in reply["error"]
    assert len(hq.gw.calls) == writes  # nothing written


def test_unexpected_check_in_closes_with_nothing_chosen(kit):
    fx = kit.fixture("unexpected-check-in")
    hq = kit.hq(fx)
    (doc,) = hq.run_once()
    app = kit.app(hq)
    base = {"dispute_key": doc["dispute_key"], "transactions": doc["transactions"], "note": "box has it"}
    status, reply = _post(app, "/api/exceptions/resolve", {**base, "chosen_txn": doc["transactions"][0]})
    assert status == 400 and "chosen_txn null" in reply["error"]
    status, reply = _post(app, "/api/exceptions/resolve", {**base, "chosen_txn": None})
    assert (status, reply["updated"]) == (200, 1)


def test_resolve_writes_hqs_copy_first_when_none_exists(kit):
    hq = kit.hq(kit.fixture("double-scan"))  # never reconciled
    status, reply = _post(kit.app(hq), "/api/exceptions/resolve", {
        "dispute_key": f"JKT-RAIN-M-BLU#001|{PACK}", "transactions": [TAKE_A, TAKE_B], "chosen_txn": TAKE_A})
    assert (status, reply["updated"]) == (200, 1)
    (doc,) = kit.exceptions(hq).values()
    assert doc["detected_by"] == "hq" and doc["status"] == "resolved" and doc["resolution"]["note"] == ""


def test_resolve_unknown_dispute_or_bad_body(kit):
    hq = kit.hq(kit.fixture("double-scan"))
    app = kit.app(hq)
    status, reply = _post(app, "/api/exceptions/resolve", {
        "dispute_key": f"JKT-RAIN-M-BLU#001|{PACK}", "transactions": [TAKE_A], "chosen_txn": TAKE_A})
    assert status == 404
    for body in ({"transactions": [TAKE_A, TAKE_B]}, {"dispute_key": "x", "transactions": []},
                 {"dispute_key": "x", "transactions": [TAKE_A], "chosen_txn": 3},
                 {"dispute_key": "x", "transactions": [TAKE_A], "note": 3}):
        assert _post(app, "/api/exceptions/resolve", body)[0] == 400, body
    assert route(app, "POST", "/api/exceptions/resolve", b"not json")[0] == 400
    assert route(app, "POST", "/api/exceptions/resolve", b"[1]")[0] == 400
