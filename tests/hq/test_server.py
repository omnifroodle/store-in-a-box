"""The HQ API and screen against FakeCapella: conservation, the tree, the staged oversell, the box panel, HTTP."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from siab_hq import queries
from siab_hq.server import LIVE_HEADER, indicator, reason, route, serve

PACK_001 = "txn::1792328410000-0000-tablet-a"


def _get(app, path):
    status, ctype, body = route(app, "GET", path)
    assert status == 200, body
    return json.loads(body) if ctype == "application/json" else body.decode()


def _post(app, path, body):
    status, _, reply = route(app, "POST", path, json.dumps(body).encode())
    return status, json.loads(reply)


def test_conservation_rows_equal_fixture_expected(kit):
    fx = kit.fixture("conservation-day")
    app = kit.app(kit.hq(fx))
    view = _get(app, "/api/conservation")
    assert view["trip"] == fx["trip"] and view["as_of"] == "2026-10-18T16:13:20Z"
    assert view["rows"] == fx["expected"]["conservation"]["with_inventory"]
    assert view["holds"] is True
    panel = _get(app, "/panels/conservation")
    assert LIVE_HEADER in panel and "HOLDS · live" in panel
    assert 'class="fail"' not in panel
    assert "Rain shell" in panel  # names come from the seed's products (D6)


def test_conservation_reports_why_a_row_fails(kit):
    app = kit.app(kit.hq(kit.fixture("overpacked")))
    view = _get(app, "/api/conservation")
    assert view["holds"] is False
    (row,) = [r for r in view["rows"] if r["sku"] == "HAT-BRIM-OS"]
    assert row["store_on_hand"] == -1 and row["holds"] is False
    panel = _get(app, "/panels/conservation")
    assert '<td class="reason">overdrawn by 1</td>' in panel
    assert "1 SKUs do not hold · live" in panel and 'class="fail"' in panel

    app = kit.app(kit.hq(kit.fixture("untraced-unit")))
    view = _get(app, "/api/conservation")
    (row,) = [r for r in view["rows"] if r["sku"] == "SOC-WOOL-M"]
    assert row["untraced"] == 1 and view["holds"] is False
    assert '<td class="reason">1 untraced</td>' in _get(app, "/panels/conservation")


def test_reason_and_indicator_words():
    row = {"store_on_hand": -2, "untraced": 1, "holds": False}
    assert reason(row) == "overdrawn by 2, 1 untraced"
    assert reason({"store_on_hand": 3, "untraced": 0, "holds": True}) == ""
    assert reason({"store_on_hand": None, "untraced": 2, "holds": False}) == "2 untraced"
    assert indicator([row, row, {"holds": True}]) == "2 SKUs do not hold · live"
    assert indicator([{"holds": True}]) == indicator([]) == "HOLDS · live"


def test_conservation_sql_returns_the_statements_run(kit):
    hq = kit.hq(kit.fixture("oversell-hq"))
    view = _get(kit.app(hq), "/api/conservation?sql=1")
    assert view["statements"] == queries.statements(hq.trip, "store-richmond")
    assert view["statements"][0]["statement"] == (
        "SELECT META(t).id AS _id, t.* FROM `retail`.`store`.`transaction` AS t WHERE t.trip = $trip ORDER BY t.hlc")
    assert "statements" not in _get(kit.app(hq), "/api/conservation")


def test_stage_hq_sale_writes_root_sale_and_reconciler_forks_it(kit, contracts):
    """pack-and-sell leaves #001 and #003 on the box. HQ sells #001 from the store: a store root beside the pack, so
    a root fork, and the reconciler writes exactly one exception for it, an oversell (HQ acts for the store, rule 8)."""
    hq = kit.hq(kit.fixture("pack-and-sell"))
    app = kit.app(hq)
    units = _get(app, "/api/stage/units")["units"]
    assert [u["unit_id"] for u in units] == ["JKT-RAIN-M-BLU#001", "JKT-RAIN-M-BLU#003"]
    assert "JKT-RAIN-M-BLU#002" not in _get(app, "/panels/stage")  # sold: not offered

    status, reply = _post(app, "/api/stage/hq-sale", {"unit_id": "JKT-RAIN-M-BLU#001"})
    assert (status, reply) == (200, {"id": "txn::1792340000000-0000-hq"})
    txn = {"_id": reply["id"], **hq.gw.docs[queries.ks("transaction")][reply["id"]]}
    assert contracts.doc_errors("transaction", txn) == []
    assert {k: txn[k] for k in ("kind", "device", "box", "from_custodian", "to_custodian", "prev_txn",
                                "from_allocation", "to_allocation")} == {
        "kind": "sale", "device": "hq", "box": None, "from_custodian": "store-richmond", "to_custodian": "customer",
        "prev_txn": None, "from_allocation": None, "to_allocation": None}
    assert txn["price"] == {"cents": 12900, "currency": "USD"}
    assert txn["tender"] == {"kind": "card_simulated", "amount": {"cents": 12900, "currency": "USD"}}
    assert txn["device_clock"] == "2026-10-18T16:13:20Z" and txn["basket"] == "00000000-0000-4000-8000-000000000100"

    (doc,) = kit.exceptions(hq).values()  # the reconciler ran after the write
    assert doc["kind"] == "oversell" and doc["dispute_key"] == "JKT-RAIN-M-BLU#001|root"
    assert doc["transactions"] == [PACK_001, reply["id"]] and doc["detected_by"] == "hq"
    assert contracts.doc_errors("exception", doc) == []
    (entry,) = _get(app, "/api/exceptions")["disputes"]
    assert entry["detectors"] == ["hq"] and entry["label"] == "open"
    assert hq.run_once() == []
    assert [c[1].collection for c in hq.gw.calls if c[0] == "upsert"] == ["transaction", "exception"]


def test_staged_sale_is_the_later_branch_when_hqs_clock_lags(kit, clock):
    """The laptop's clock is behind the tablets'. HQ's HLC has read the pack and the sale, so its own sale still
    comes after them and the fork is an oversell, not a double scan."""
    clock.ms = 1792320000000  # before every fixture hlc
    hq = kit.hq(kit.fixture("pack-and-sell"), clock)
    status, reply = _post(kit.app(hq), "/api/stage/hq-sale", {"unit_id": "JKT-RAIN-M-BLU#001"})
    assert (status, reply) == (200, {"id": "txn::1792329000000-0001-hq"})  # after the latest hlc HQ read
    (doc,) = kit.exceptions(hq).values()
    assert doc["kind"] == "oversell"


def test_stage_refuses_what_the_box_does_not_hold(kit):
    hq = kit.hq(kit.fixture("pack-and-sell"))
    app = kit.app(hq)
    for body in ({"unit_id": "JKT-RAIN-M-BLU#002"}, {"unit_id": "JKT-RAIN-M-BLU#999"}, {},
                 {"unit_id": "JKT-RAIN-M-BLU#001", "price": {"cents": -1, "currency": "USD"}},
                 {"unit_id": "JKT-RAIN-M-BLU#001", "price": {"cents": 100, "currency": "EUR"}},
                 {"unit_id": "JKT-RAIN-M-BLU#001", "price": 129}):
        assert _post(app, "/api/stage/hq-sale", body)[0] == 400, body
    assert hq.gw.calls == []
    status, reply = _post(app, "/api/stage/hq-sale",
                          {"unit_id": "JKT-RAIN-M-BLU#003", "price": {"cents": 9900, "currency": "USD"}})
    assert status == 200
    assert hq.gw.docs[queries.ks("transaction")][reply["id"]]["price"] == {"cents": 9900, "currency": "USD"}


@pytest.mark.parametrize("name", ["conservation-day", "split-and-merge", "second-level-take"])
def test_tree_matches_allocation_counts(name, kit):
    hq = kit.hq(kit.fixture(name))
    tree = _get(kit.app(hq), "/api/tree")
    state = hq.snapshot().state
    counts = {a["id"]: a["count"] for n in tree["nodes"] for a in n["allocations"]}
    assert counts == dict(state.allocation_counts)
    assert tree["root"] == "store-richmond" and tree["nodes"][0] == {
        **tree["nodes"][0], "custodian": "store-richmond", "parent": None}
    parents = {n["custodian"]: n["parent"] for n in tree["nodes"]}
    assert parents.get("box-07") in (None, "store-richmond")
    held = {(n["custodian"], s): q for n in tree["nodes"] for s, q in n["held"].items()}
    assert held == {k: v for k, v in state.counts.items() if v >= 1}
    panel = _get(kit.app(hq), "/panels/tree")
    assert "box-07" in panel


def test_tree_puts_a_second_level_take_under_the_tablet(kit):
    hq = kit.hq(kit.fixture("second-level-take"))
    kit.put(hq, "allocation", {
        "_id": "alloc::1792328500000-0000-phone-1", "v": 1, "type": "allocation", "trip": hq.trip, "box": "box-07",
        "sku": "JKT-RAIN-M-BLU", "custodian": "phone-1", "parent": None, "from_custodian": "tablet-b",
        "opened_by": "phone-1", "opened_at": "1792328500000-0000-phone-1", "closed_at": None, "status": "active"})
    hq.run_once()
    parents = {n["custodian"]: n["parent"] for n in _get(kit.app(hq), "/api/tree")["nodes"]}
    assert parents["phone-1"] == "tablet-b"


def test_box_panel(kit):
    hq = kit.hq(kit.fixture("oversell-hq"))
    assert _get(kit.app(hq), "/api/box") == {"configured": False}
    assert "box not configured" in _get(kit.app(hq), "/panels/box")

    status = {"box": "box-07", "uplink": {"reachable": True, "cut": True}, "bytes": {"in": 1200, "out": 34567}}
    app = kit.app(hq, box_status_url="http://box.test/status", http_get=lambda url: status)
    assert _get(app, "/api/box") == status
    panel = _get(app, "/panels/box")
    assert "out 34,567 B" in panel and "uplink CUT" in panel

    def refused(url):
        raise httpx.ConnectError("refused")

    app = kit.app(hq, box_status_url="http://box.test/status", http_get=refused)
    code, _, body = route(app, "GET", "/api/box")
    assert code == 502 and json.loads(body)["reachable"] is False
    assert "box unreachable" in _get(app, "/panels/box")


def test_screen_and_static_files(kit):
    app = kit.app(kit.hq(kit.fixture("oversell-hq")))
    page = _get(app, "/")
    assert '<script src="/hq.js"></script>' in page
    for panel in ("conservation", "tree", "exceptions", "stage", "box"):
        assert f'id="{panel}"' in page
    assert "/panels/" in _get(app, "/hq.js")
    assert route(app, "GET", "/hq.css")[1].startswith("text/css")


def test_reconcile_endpoints_unknown_paths_and_trips(kit):
    hq = kit.hq(kit.fixture("oversell-hq"))
    app = kit.app(hq)
    assert _get(app, "/api/reconcile/status")["last_run"] is None
    status, reply = _post(app, "/api/reconcile/run", {})
    assert status == 200 and reply["exceptions_written"] == 1 and reply["forks_open"] == 1
    assert route(app, "GET", "/api/nope")[0] == 404
    assert route(app, "POST", "/api/nope")[0] == 404
    assert route(app, "DELETE", "/api/tree")[0] == 405
    assert route(app, "GET", "/api/conservation?trip=trip-nope")[0] == 404
    other = kit.fixture("double-scan")
    assert route(app, "GET", f"/api/conservation?trip={other['trip']}")[0] == 200


def test_http_server_on_loopback(kit):
    app = kit.app(kit.hq(kit.fixture("oversell-hq")))

    async def exchange(request: bytes) -> bytes:
        server = await serve(app, 0)
        port = server.sockets[0].getsockname()[1]
        assert server.sockets[0].getsockname()[0] == "127.0.0.1"
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(request)
        await writer.drain()
        reply = await reader.read()
        writer.close()
        server.close()
        await server.wait_closed()
        return reply

    reply = asyncio.run(exchange(b"GET /api/reconcile/status HTTP/1.1\r\nHost: x\r\n\r\n"))
    head, _, body = reply.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200 OK") and b"Cache-Control: no-store" in head
    assert json.loads(body)["last_run"] is None
    payload = json.dumps({"unit_id": "JKT-RAIN-M-BLU#999"}).encode()
    reply = asyncio.run(exchange(b"POST /api/stage/hq-sale HTTP/1.1\r\nContent-Length: "
                                 + str(len(payload)).encode() + b"\r\n\r\n" + payload))
    assert reply.startswith(b"HTTP/1.1 400 Bad Request")
