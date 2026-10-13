"""The golden fixture runner: ``contracts/fixtures/ledger/*.json`` against this implementation.

Each fixture's transactions and resolutions are ingested (rule 0) and the accepted ones reduced, then
``exceptions_for`` runs with the fixture's detector and ``conservation`` runs with the inventory (when the fixture has
one) and without it; the result, with the drops, must equal ``expected`` exactly. A fixture marked
``order_independent`` is re-run with its transactions and resolutions shuffled (seeded), and with duplicates, and must
give the same answer every time, ``drops`` included. ``report`` runs the same over a directory of differential sets
(``scripts/ledger_diff.py``) for the comparison with the Swift port.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from .chain import reduce
from .conservation import conservation
from .exceptions import exceptions_for
from .ingest import ingest

SHUFFLES = 8
"""Shuffled re-runs per order-independent fixture (besides the reversed order)."""


def default_fixtures_dir() -> Path:
    """``contracts/fixtures/ledger`` of the repository the working directory (else this package) is in."""
    for start in (Path.cwd().resolve(), Path(__file__).resolve()):
        for parent in (start, *start.parents):
            candidate = parent / "contracts" / "fixtures" / "ledger"
            if candidate.is_dir():
                return candidate
    raise FileNotFoundError("contracts/fixtures/ledger not found; pass --fixtures DIR")


def load_fixtures(directory: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(Path(directory).glob("*.json"))]


def run(fixture: dict, transactions: Sequence[dict] | None = None, resolutions: Sequence[dict] | None = None) -> dict:
    """The implementation's answer to ``fixture``, shaped like its ``expected``: rule 0, then the reducer over what
    it accepted. ``fixture`` may also be a differential set, which has no ``expected`` and names its ``detector``."""
    txns = fixture["transactions"] if transactions is None else transactions
    res = fixture["resolutions"] if resolutions is None else resolutions
    txn_in, res_in = ingest(txns, "transaction"), ingest(res, "exception")
    state = reduce(txn_in.accepted, res_in.accepted, store=fixture["store"])
    detector = fixture["expected"]["exceptions"]["detector"] if "expected" in fixture else fixture["detector"]
    with_inventory = None
    if fixture["inventory"] is not None:
        with_inventory = [r.to_json() for r in conservation(state, fixture["store"], fixture["inventory"])]
    drops = sorted(txn_in.drops + res_in.drops, key=lambda d: (d.collection, d.id))
    return {
        **state.to_json(),
        "exceptions": {
            "detector": detector,
            "docs": exceptions_for(state, detector, fixture["trip"], fixture["box"]),
        },
        "conservation": {
            "with_inventory": with_inventory,
            "venue_only": [r.to_json() for r in conservation(state, fixture["store"], None)],
        },
        "drops": [d.key() for d in drops],
    }


def first_difference(expected, actual, path: str = "expected") -> str | None:
    """A one-line description of the first place ``actual`` differs from ``expected``, or None."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in expected:
            if key not in actual:
                return f"{path}.{key}: missing"
        for key in actual:
            if key not in expected:
                return f"{path}.{key}: unexpected {json.dumps(actual[key])}"
        if list(expected) != list(actual) and path.endswith(("units", "allocation_counts", "in_custody")):
            return f"{path}: keys in order {list(actual)}, expected {list(expected)}"
        for key in expected:
            diff = first_difference(expected[key], actual[key], f"{path}.{key}")
            if diff:
                return diff
        return None
    if isinstance(expected, list) and isinstance(actual, list):
        for i, (e, a) in enumerate(zip(expected, actual, strict=False)):
            diff = first_difference(e, a, f"{path}[{i}]")
            if diff:
                return diff
        if len(expected) != len(actual):
            return f"{path}: {len(actual)} items, expected {len(expected)}"
        return None
    if type(expected) is not type(actual) or expected != actual:
        return f"{path}: got {json.dumps(actual)}, expected {json.dumps(expected)}"
    return None


def orderings(fixture: dict, seed: int) -> Iterator[tuple[str, list[dict], list[dict]]]:
    """(label, transactions, resolutions) re-orderings of an order-independent fixture, deterministic per seed."""
    txns, res = list(fixture["transactions"]), list(fixture["resolutions"])
    yield "reversed", txns[::-1], res[::-1]
    for i in range(SHUFFLES):
        rng = random.Random(f"{seed}/{fixture['name']}/{i}")
        t, r = txns[:], res[:]
        if i % 2:  # every other run also delivers some documents twice
            t += rng.sample(txns, k=max(1, len(txns) // 3))
            r += r[:1]
        rng.shuffle(t)
        rng.shuffle(r)
        yield f"shuffle {i} (seed {seed})", t, r


@dataclass(frozen=True)
class Outcome:
    name: str
    difference: str | None

    @property
    def line(self) -> str:
        return f"PASS {self.name}" if self.difference is None else f"FAIL {self.name}: {self.difference}"


def check(fixture: dict, seed: int = 0) -> Outcome:
    diff = first_difference(fixture["expected"], run(fixture))
    if diff is None and fixture["order_independent"]:
        for label, txns, res in orderings(fixture, seed):
            diff = first_difference(fixture["expected"], run(fixture, txns, res))
            if diff is not None:
                diff = f"{label}: {diff}"
                break
    return Outcome(fixture["name"], diff)


def check_all(directory: Path, seed: int = 0) -> list[Outcome]:
    return [check(fixture, seed) for fixture in load_fixtures(directory)]


def canonical(value) -> str:
    """The differential report's serialisation: sorted keys, no spaces, ASCII (the Swift runner writes the same)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def report(sets_dir: Path) -> dict[str, dict]:
    """``run`` over every ``*.json`` differential set in ``sets_dir``, keyed by file name."""
    return {p.name: run(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(Path(sets_dir).glob("*.json"))}
