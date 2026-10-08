"""Shared helpers for the ledger tests: the golden fixtures and the contract validator, loaded from the repository."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LEDGER_FIXTURES = REPO / "contracts" / "fixtures" / "ledger"


def _load(name: str) -> dict:
    return json.loads((LEDGER_FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def fixture():
    """``fixture(name)`` returns a fresh copy of ``contracts/fixtures/ledger/<name>.json``."""
    return _load


@pytest.fixture(scope="session")
def validator():
    """``scripts/check_contracts.py`` as a module, with its ``Contracts`` loaded from ``contracts/``."""
    spec = importlib.util.spec_from_file_location("check_contracts", REPO / "scripts" / "check_contracts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, module.Contracts.load(REPO / "contracts")


class FakeClock:
    """Virtual milliseconds: the test sets and moves the time; nothing reads the wall clock."""

    def __init__(self, ms: int):
        self.ms = ms

    def __call__(self) -> int:
        return self.ms

    def advance(self, ms: int) -> None:
        self.ms += ms


@pytest.fixture
def clock():
    return FakeClock(1792328400000)
