"""The reconciler: one HQ exception per open fork, idempotent by id, on virtual time; HQ's clock; the CLI."""

from __future__ import annotations

import asyncio
import io

import pytest

from siab_capella.provision import ks
from siab_hq.__main__ import main
from siab_ledger import exception_id


def _as_hq(doc: dict) -> dict:
    """A detector's expected document as HQ writes it: its own id, no box, detector hq."""
    out = {**doc, "_id": exception_id("hq", doc["unit_id"], doc["transactions"]), "box": None, "detected_by": "hq"}
    return out


@pytest.mark.parametrize("name", ["oversell-hq", "double-scan"])
def test_reconciler_writes_one_exception_per_open_fork(name, kit, contracts):
    fx = kit.fixture(name)
    hq = kit.hq(fx)
    written = hq.run_once()
    (expected,) = fx["expected"]["exceptions"]["docs"]
    assert [d["_id"] for d in written] == [_as_hq(expected)["_id"]]
    (doc,) = written
    assert {k: v for k, v in doc.items() if k != "detected_at"} == _as_hq(expected)
    assert doc["detected_at"].endswith("-hq")
    stored = kit.exceptions(hq)[doc["_id"]]
    assert stored == doc
    assert contracts.doc_errors("exception", stored) == []
    assert kit.writes(hq, "exception") == [doc["_id"]]
    assert hq.status.to_json() == {"last_run": "2026-10-18T16:13:20Z", "exceptions_written": 1, "forks_open": 1,
                                   "last_error": None}


def test_reconciler_is_idempotent_across_runs(kit, clock):
    hq = kit.hq(kit.fixture("oversell-hq"), clock)
    slept: list[float] = []

    async def virtual_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(int(seconds * 1000))

    asyncio.run(hq.run_every(3, sleep=virtual_sleep, ticks=3))
    assert slept == [3, 3, 3]
    assert len(kit.writes(hq, "exception")) == 1  # the first tick wrote it; the next two found its id
    assert hq.status.exceptions_written == 1
    assert hq.status.last_run == "2026-10-18T16:13:29Z"
    assert hq.run_once() == []


def test_reconciler_loop_outlives_a_failed_run(kit, clock):
    hq = kit.hq(kit.fixture("oversell-hq"), clock)
    handler = hq.gw.query_handler
    calls = {"n": 0}

    def flaky(statement, params):
        calls["n"] += 1
        if calls["n"] == 1:  # the first run fails at its first read
            raise ConnectionError("Capella unreachable")
        return handler(statement, params)

    hq.gw.query_handler = flaky

    async def virtual_sleep(seconds: float) -> None:
        clock.advance(int(seconds * 1000))

    asyncio.run(hq.run_every(3, sleep=virtual_sleep, ticks=1))
    assert hq.status.last_error == "ConnectionError: Capella unreachable"
    asyncio.run(hq.run_every(3, sleep=virtual_sleep, ticks=1))
    assert hq.status.last_error is None and hq.status.exceptions_written == 1


def test_reconciler_writes_nothing_for_a_settled_or_withdrawn_fork(kit):
    for name in ("resolved-fork", "latest-resolution-chooses-nothing", "fork-inside-set-aside-branch"):
        hq = kit.hq(kit.fixture(name))
        assert hq.run_once() == [], name


def test_reconciler_writes_unexpected_check_ins_and_foreign_movements(kit, contracts):
    for name in ("unexpected-check-in", "foreign-sale", "foreign-check-out"):
        fx = kit.fixture(name)
        hq = kit.hq(fx)
        written = hq.run_once()
        assert [d["_id"] for d in written] == [_as_hq(d)["_id"] for d in fx["expected"]["exceptions"]["docs"]]
        assert all(contracts.doc_errors("exception", d) == [] for d in written)


def test_hq_clock_is_ahead_of_every_resolution_it_read(kit, clock):
    """A restarted HQ with its wall clock behind its earlier decisions still orders the next one after them."""
    clock.ms = 1792328400000  # before the fixture's resolutions
    hq = kit.hq(kit.fixture("latest-resolution-chooses-nothing"), clock)
    hq.run_once()
    assert hq.hlc.last == "1792330500000-0000-hq"
    assert hq.hlc.now() == "1792330500000-0001-hq"
    clock.ms = 1792340000000
    assert hq.hlc.now() == "1792340000000-0000-hq"


def test_reconcile_once_dry_run_prints_planned_ids_and_writes_nothing():
    out = io.StringIO()
    code = main(["reconcile", "--once", "--dry-run"], env={"SIAB_HQ_FAKE": "oversell-hq"}, out=out)
    assert code == 0
    assert out.getvalue() == "would write exc::hq::JKT-RAIN-M-BLU#001::57cf515b\n"


def test_reconcile_once_writes_through_the_gateway(kit):
    hq = kit.hq(kit.fixture("double-scan"))
    out = io.StringIO()
    assert main(["reconcile", "--once", "--trip", hq.trip], env={}, gateway=hq.gw, out=out) == 0
    assert out.getvalue() == "wrote exc::hq::JKT-RAIN-M-BLU#001::111c7a4e\n"
    assert main(["reconcile", "--once", "--trip", hq.trip], env={}, gateway=hq.gw, out=out) == 0
    assert out.getvalue().endswith("nothing to write for trip-2026-10-18-riverfest\n")
    assert len([c for c in hq.gw.calls if c[0] == "upsert" and c[1] == ks("exception")]) == 1


def test_cli_refuses_without_credentials_or_trip():
    out = io.StringIO()
    assert main(["reconcile", "--once"], env={"SIAB_TRIP": "trip-x"}, out=out) == 1
    assert "CAPELLA_CONN_STRING" in out.getvalue() and "SIAB_HQ_FAKE" in out.getvalue()
    out = io.StringIO()
    assert main(["reconcile", "--once", "--trip", "trip-nope"], env={"SIAB_HQ_FAKE": "oversell-hq"}, out=out) == 1
    assert "trip::trip-nope" in out.getvalue()
