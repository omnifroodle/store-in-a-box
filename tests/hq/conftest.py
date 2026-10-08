"""Fakes for the HQ tests: WS2's FakeCapella loaded from WS1's ledger fixtures, a virtual clock, the validator."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from siab_capella.provision import ks
from siab_hq.queries import body, fake_from_fixture
from siab_hq.reconcile import Hq
from siab_hq.server import App

REPO = Path(__file__).resolve().parents[2]
LEDGER = REPO / "contracts" / "fixtures" / "ledger"
START_MS = 1792340000000  # after every fixture's hlc


class FakeClock:
    """Virtual milliseconds: the test sets and moves the time; nothing reads the wall clock."""

    def __init__(self, ms: int):
        self.ms = ms

    def __call__(self) -> int:
        return self.ms

    def advance(self, ms: int) -> None:
        self.ms += ms


class Kit:
    REPO = REPO

    @staticmethod
    def fixture(name: str) -> dict:
        return json.loads((LEDGER / f"{name}.json").read_text())

    @staticmethod
    def hq(fixture: dict, clock=None, *, drop: tuple[str, ...] = ()) -> Hq:
        """An Hq over a FakeCapella holding ``fixture`` (minus the transactions in ``drop``)."""
        fx = copy.deepcopy(fixture)
        fx["transactions"] = [t for t in fx["transactions"] if t["_id"] not in drop]
        baskets = iter(f"00000000-0000-4000-8000-{n:012d}" for n in range(100, 1000))
        return Hq(fake_from_fixture(fx), fx["trip"], clock or FakeClock(START_MS), new_basket=lambda: next(baskets))

    @staticmethod
    def app(hq: Hq, **kw) -> App:
        return App(hq, **kw)

    @staticmethod
    def exceptions(hq: Hq) -> dict[str, dict]:
        return {i: {"_id": i, **d} for i, d in hq.gw.docs.get(ks("exception"), {}).items()}

    @staticmethod
    def put(hq: Hq, collection: str, doc: dict) -> None:
        hq.gw.docs.setdefault(ks(collection), {})[doc["_id"]] = body(doc)

    @staticmethod
    def writes(hq: Hq, collection: str) -> list[str]:
        return [c[2] for c in hq.gw.calls if c[0] == "upsert" and c[1] == ks(collection)]


@pytest.fixture
def kit() -> Kit:
    return Kit()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START_MS)


@pytest.fixture(scope="session")
def contracts():
    """``scripts/check_contracts.py``'s ``Contracts``, loaded from ``contracts/``: what HQ writes must validate."""
    spec = importlib.util.spec_from_file_location("check_contracts", REPO / "scripts" / "check_contracts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Contracts.load(REPO / "contracts")
