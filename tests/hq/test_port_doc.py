"""ports/hq.md is the contract WS7 and WS8 read: the app's JSON must match its examples' shapes."""

from __future__ import annotations

import json
import re

from siab_hq.server import route

ALLOC = "alloc::1792328400000-0000-tablet-a"


def _doc(kit) -> str:
    return (kit.REPO / "ports" / "hq.md").read_text(encoding="utf-8")


def _example(doc: str, heading: str):
    """The first ```json block after the heading line that contains `heading`."""
    start = next(m.end() for m in re.finditer(r"^#+ .*$", doc, re.MULTILINE) if heading in m.group(0))
    block = re.search(r"```json\n(.*?)```", doc[start:], re.DOTALL)
    return json.loads(block.group(1))


def shape(value):
    """Keys in order and value types, recursively; null is its own type."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__


def _get(app, path):
    status, _, body = route(app, "GET", path)
    assert status == 200, body
    return json.loads(body)


def _post(app, path, body):
    status, _, reply = route(app, "POST", path, json.dumps(body).encode())
    assert status == 200, reply
    return json.loads(reply)


def test_conservation_tree_and_status_match_port_doc(kit):
    fx = kit.fixture("overpacked")
    hq = kit.hq(fx)
    kit.put(hq, "allocation", {
        "_id": ALLOC, "v": 1, "type": "allocation", "trip": hq.trip, "box": "box-07", "sku": "HAT-BRIM-OS",
        "custodian": "box-07", "parent": None, "from_custodian": "store-richmond", "opened_by": "tablet-a",
        "opened_at": "1792328400000-0000-tablet-a", "closed_at": None, "status": "active"})
    app = kit.app(hq)
    doc = _doc(kit)
    assert shape(_get(app, "/api/conservation")) == shape(_example(doc, "GET /api/conservation"))
    tree, example = _get(app, "/api/tree"), _example(doc, "GET /api/tree")
    assert list(tree) == list(example) and tree["root"] == example["root"]
    store, box = tree["nodes"][0], next(n for n in tree["nodes"] if n["custodian"] == "box-07")
    for got, want in ((store, example["nodes"][0]), (box, example["nodes"][1])):
        assert {k: shape(v) for k, v in got.items() if k != "held"} == {
            k: shape(v) for k, v in want.items() if k != "held"}
        assert all(isinstance(q, int) for q in got["held"].values())
    assert shape(_get(app, "/api/reconcile/status"))["last_run"] == "str"
    assert shape(_get(app, "/api/reconcile/status")) == shape(_example(doc, "GET /api/reconcile/status"))
    assert _get(app, "/api/box") == _example(doc, "GET /api/box")


def test_exceptions_resolve_and_stage_match_port_doc(kit):
    fx = kit.fixture("pack-and-sell")
    hq = kit.hq(fx)
    app = kit.app(hq)
    doc = _doc(kit)
    assert shape(_get(app, "/api/stage/units")) == shape(_example(doc, "GET /api/stage/units"))
    staged = _post(app, "/api/stage/hq-sale", {"unit_id": "JKT-RAIN-M-BLU#001"})
    assert shape(staged) == shape(_example(doc, "POST /api/stage/hq-sale"))

    view = _get(app, "/api/exceptions")
    example = _example(doc, "GET /api/exceptions")
    assert list(view) == list(example)
    (entry,) = view["disputes"]
    assert list(entry) == list(example["disputes"][0])
    assert {k: shape(v) for k, v in entry.items() if k not in ("transactions", "branches", "documents")} == {
        k: shape(v) for k, v in example["disputes"][0].items() if k not in ("transactions", "branches", "documents")}
    assert list(entry["branches"][0]) == ["txn", "leaf"]

    reply = _post(app, "/api/exceptions/resolve", {
        "dispute_key": entry["dispute_key"], "transactions": [t["_id"] for t in entry["transactions"]],
        "chosen_txn": entry["transactions"][0]["_id"], "note": "the venue's sale stands"})
    assert shape(reply) == shape(_example(doc, "POST /api/exceptions/resolve"))
    assert shape(_post(app, "/api/exceptions/close-superseded", {})) == shape(
        _example(doc, "POST /api/exceptions/close-superseded"))


def test_port_doc_names_every_route_the_server_answers(kit):
    doc = _doc(kit)
    server = (kit.REPO / "src" / "siab_hq" / "server.py").read_text(encoding="utf-8")
    routes = set(re.findall(r'"(/api/[a-z/-]+)"', server))
    assert routes and all(r in doc for r in routes), sorted(r for r in routes if r not in doc)
    assert "ports/hq.md" in (kit.REPO / "ports" / "README.md").read_text(encoding="utf-8") or "(hq.md)" in (
        kit.REPO / "ports" / "README.md").read_text(encoding="utf-8")
