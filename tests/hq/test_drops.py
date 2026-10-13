"""Rule 0 at HQ (decision 010): invalid rows are dropped, counted, logged and shown; HQ never writes an invalid one."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from siab_capella.provision import ks
from siab_hq import reconcile
from siab_hq.__main__ import connect
from siab_hq.reconcile import DropLog, Hq
from siab_hq.server import App, indicator, route
from siab_ledger import Drop

TAKE = "txn::1792328510000-0000-tablet-a"


def _get(app: App, path: str):
    status, _, body = route(app, "GET", path)
    assert status == 200, body
    return json.loads(body) if path.startswith("/api/") else body.decode()


def _upserts(hq: Hq) -> list[tuple]:
    return [c for c in hq.gw.calls if c[0] == "upsert"]


def test_indicator_wording_is_byte_for_byte():
    holds, fails = {"holds": True}, {"holds": False}
    assert indicator([holds]) == "HOLDS · live"
    assert indicator([holds], 0) == "HOLDS · live"
    assert indicator([holds], 2) == "HOLDS · 2 dropped · live"
    assert indicator([fails, holds]) == "1 SKUs do not hold · live"
    assert indicator([fails, fails], 1) == "2 SKUs do not hold · 1 dropped · live"
    assert indicator([], 3) == "HOLDS · 3 dropped · live"


def test_conservation_reports_drops(clock, caplog):
    gw, trip = connect({"SIAB_HQ_FAKE": "drop-transaction-missing-field"})
    app = App(Hq(gw, trip, clock))
    with caplog.at_level(logging.WARNING, logger="siab_hq.ingest"):
        view = _get(app, "/api/conservation")
    assert view["dropped"] == 1 and view["holds"] is True
    (entry,) = view["drops"]
    assert entry == {"id": TAKE, "collection": "transaction", "code": "missing_field",
                     "detail": "device_clock: required", "source": "capella",
                     "first_seen": "2026-10-18T16:13:20Z", "last_seen": "2026-10-18T16:13:20Z"}
    (row,) = view["rows"]
    assert row["in_custody"] == {"box-07": 1} and row["store_on_hand"] == 11  # the take is not counted
    assert _get(app, "/api/reconcile/status")["dropped"] == 1
    panel = _get(app, "/panels/conservation")
    assert '<p class="indicator holds">HOLDS · 1 dropped · live</p>' in panel
    assert '<p class="dropped">1 documents dropped</p>' in panel
    assert f"<li>transaction {TAKE} · missing field · 2026-10-18T16:13:20Z</li>" in panel
    assert [r.message for r in caplog.records] == [
        f"dropped transaction {TAKE}: missing_field, device_clock: required (source capella)"]

    gw, trip = connect({"SIAB_HQ_FAKE": "drop-and-untraced"})
    app = App(Hq(gw, trip, clock))
    panel = _get(app, "/panels/conservation")
    assert '<p class="indicator fails">1 SKUs do not hold · 1 dropped · live</p>' in panel
    assert "txn::1792334200000-0000-tablet-b · missing field" in panel


def test_no_drops_no_dropped_line(kit, clock):
    app = App(kit.hq(kit.fixture("double-scan"), clock))
    view = _get(app, "/api/conservation")
    assert view["dropped"] == 0 and view["drops"] == []
    panel = _get(app, "/panels/conservation")
    assert "dropped" not in panel


@pytest.mark.parametrize("newer", ["drop-newer-version", "drop-unknown-kind", "drop-rule-sku-mismatch"])
def test_each_code_reads_in_words(newer, clock):
    gw, trip = connect({"SIAB_HQ_FAKE": newer})
    panel = _get(App(Hq(gw, trip, clock)), "/panels/conservation")
    words = {"drop-newer-version": "newer schema: update the app", "drop-unknown-kind": "invalid value",
             "drop-rule-sku-mismatch": "rule"}[newer]
    assert f"<li>transaction {TAKE} · {words} · " in panel


def test_reconciler_survives_invalid_rows(kit, clock, caplog):
    """Rows that made the reducer (and the fake's ORDER BY) raise KeyError: no hlc, no prev_txn, no kind."""
    hq = kit.hq(kit.fixture("double-scan"), clock)
    kit.put(hq, "transaction", {"_id": "txn::1792328999000-0000-tablet-b", "v": 1, "type": "transaction",
                                "trip": hq.trip, "unit_id": "JKT-RAIN-M-BLU#001"})
    hq.gw.docs[ks("transaction")]["txn::garbage"] = {"trip": hq.trip, "hlc": 7}

    async def virtual_sleep(seconds: float) -> None:
        clock.advance(int(seconds * 1000))

    seen = []
    with caplog.at_level(logging.WARNING, logger="siab_hq.ingest"):
        for _ in range(3):
            asyncio.run(hq.run_every(3, sleep=virtual_sleep, ticks=1))
            assert hq.status.last_error is None
            assert hq.status.dropped == 2
            assert len(hq.drop_log) == 2
            seen.append(hq.drop_log.newest()[0]["last_seen"])
    assert seen == ["2026-10-18T16:13:23Z", "2026-10-18T16:13:26Z", "2026-10-18T16:13:29Z"]
    codes = {e["id"]: e["code"] for e in hq.drop_log.newest()}
    assert codes == {"txn::1792328999000-0000-tablet-b": "missing_field", "txn::garbage": "wrong_type"}
    assert {e["first_seen"] for e in hq.drop_log.newest()} == {"2026-10-18T16:13:23Z"}
    assert len(caplog.records) == 2  # each new entry once, not once per tick
    assert hq.status.exceptions_written == 1  # the double scan's exception, from the valid rows


def test_hq_never_overwrites_a_document_it_cannot_read(kit, clock):
    fx = kit.fixture("oversell-hq")
    hq = kit.hq(fx, clock)
    planned = hq.run_once(dry_run=True)
    (doc,) = planned
    broken = {k: v for k, v in doc.items() if k != "proposed_resolution"}
    kit.put(hq, "exception", broken)  # HQ's own id, a body it cannot read
    assert hq.run_once() == []
    assert _upserts(hq) == []
    assert hq.status.dropped == 1
    assert hq.drop_log.newest()[0]["id"] == doc["_id"]


def test_hq_refuses_to_write_an_invalid_document(kit, clock, monkeypatch):
    fx = kit.fixture("oversell-hq")
    hq = kit.hq(fx, clock)
    hq.run_once()
    hq.gw.calls.clear()
    app = App(hq)
    entry = _get(app, "/api/exceptions")["disputes"][0]
    request = {"dispute_key": entry["dispute_key"], "transactions": [t["_id"] for t in entry["transactions"]],
               "chosen_txn": entry["transactions"][0]["_id"], "note": "the venue's sale stands"}

    real = Hq._resolution
    monkeypatch.setattr(Hq, "_resolution", lambda self, chosen, note: {**real(self, chosen, note), "by": "HQ"})
    status, _, body = route(app, "POST", "/api/exceptions/resolve", json.dumps(request).encode())
    assert status == 400
    assert json.loads(body)["error"].startswith("HQ would write an invalid exception: resolution.by: ")
    assert _upserts(hq) == []
    monkeypatch.setattr(Hq, "_resolution", real)
    status, _, _ = route(app, "POST", "/api/exceptions/resolve", json.dumps(request).encode())
    assert status == 200 and _upserts(hq)

    # The staged sale: a basket that is not a UUID would make the transaction invalid.
    hq = kit.hq(kit.fixture("pack-and-sell"), clock)
    hq.new_basket = lambda: "basket-1"
    status, _, body = route(App(hq), "POST", "/api/stage/hq-sale", json.dumps({"unit_id": "JKT-RAIN-M-BLU#001"})
                            .encode())
    assert status == 400 and "HQ would write an invalid transaction: basket: " in json.loads(body)["error"]
    assert _upserts(hq) == []

    # The reconciler's own exceptions: refused before the first upsert, and the loop records why.
    hq = kit.hq(fx, clock)
    real_for = reconcile.exceptions_for
    monkeypatch.setattr(reconcile, "exceptions_for",
                        lambda *a, **k: [{**d, "note": "x"} for d in real_for(*a, **k)])

    async def virtual_sleep(seconds: float) -> None:
        clock.advance(int(seconds * 1000))

    asyncio.run(hq.run_every(3, sleep=virtual_sleep, ticks=1))
    assert hq.status.last_error == "BadRequest: HQ would write an invalid exception: note: unknown field"
    assert _upserts(hq) == []


def test_drop_log_is_bounded():
    log = DropLog()
    for batch in range(5):  # 250 ids, 50 per read, each read later than the last
        drops = [Drop(f"txn::{batch * 50 + i:04d}", "transaction", "version", "v: 2, not 1") for i in range(50)]
        log.record(drops, f"2026-10-18T14:0{batch}:00Z")
    assert len(log) == 200
    ids = {e["id"] for e in log.newest()}
    assert ids == {f"txn::{n:04d}" for n in range(50, 250)}  # the oldest 50 evicted
    assert log.newest()[0]["last_seen"] == "2026-10-18T14:04:00Z"
    # Re-seeing an old entry keeps it; the least recently seen goes instead.
    log.record([Drop("txn::0050", "transaction", "version", "v: 2, not 1")], "2026-10-18T14:05:00Z")
    log.record([Drop("txn::9999", "exception", "rule", "x")], "2026-10-18T14:05:00Z")
    assert len(log) == 200
    entries = {e["id"]: e for e in log.newest()}
    assert "txn::0050" in entries and "txn::0051" not in entries and "txn::9999" in entries
    assert entries["txn::0050"]["first_seen"] == "2026-10-18T14:01:00Z"


def test_drop_log_is_bounded_at_hq(kit, clock):
    hq = kit.hq(kit.fixture("double-scan"), clock)
    pack = kit.fixture("double-scan")["transactions"][0]

    def put_invalid(numbers):
        for n in numbers:
            hlc = f"{1792330000000 + n}-0000-tablet-a"
            kit.put(hq, "transaction", {**pack, "_id": f"txn::{hlc}", "hlc": hlc, "v": 2})

    put_invalid(range(50))
    hq.run_once()
    clock.advance(3000)
    put_invalid(range(50, 250))
    hq.run_once()
    assert hq.status.dropped == 250
    assert len(hq.drop_log) == 200
    view = _get(App(hq), "/api/conservation")
    assert view["dropped"] == 250 and len(view["drops"]) == 50
    assert all(e["last_seen"] == "2026-10-18T16:13:23Z" for e in view["drops"])
