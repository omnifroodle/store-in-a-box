"""The differential test (decision 010, WS10): both ledger ports on the same inputs nobody wrote expectations for.

Usage (from the repository root, in the project's environment):
    uv run python scripts/ledger_diff.py generate --seed N --out DIR [--per-fixture K]
    uv run python -m siab_ledger report --sets DIR --out python.json      (the Swift runner writes swift.json)
    uv run python scripts/ledger_diff.py compare python.json swift.json

generate: for every fixture in contracts/fixtures/ledger/, K sets DIR/<fixture>-<k>.json, each
{name, trip, box, store, detector, inventory, transactions, resolutions} (the fixture without expected, description
and order_independent; detector is expected.exceptions.detector). -0 is the fixture's order, -1 reversed, -2 up to
-K/2 shuffled with duplicates (a third of the transactions and the first resolution delivered twice), and from -K/2
on the same, corrupted: a random 20% of the documents each get one mutation from MUTATIONS. Seeded by
"<seed>/<name>/<k>", so a failure is reproducible from its seed.

compare: PASS <set> or FAIL <set>: <first difference> per set, in file-name order; exit 1 on any failure.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from collections.abc import Callable
from pathlib import Path

from siab_ledger.fixtures import default_fixtures_dir, first_difference, load_fixtures
from siab_ledger.ingest import default_contracts_dir

DEFAULT_PER_FIXTURE = 6
CORRUPT_SHARE = 0.2
SET_KEYS = ("name", "trip", "box", "store", "detector", "inventory", "transactions", "resolutions")
SET_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "differential set",
    "type": "object",
    "additionalProperties": False,
    "required": list(SET_KEYS),
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "trip": {"type": "string"},
        "box": {"type": ["string", "null"]},
        "store": {"type": "string"},
        "detector": {"type": "string"},
        "inventory": {"type": ["array", "null"], "items": {"type": "object"}},
        "transactions": {"type": "array", "items": {"type": "object", "required": ["_id"]}},
        "resolutions": {"type": "array", "items": {"type": "object", "required": ["_id"]}},
    },
}

Mutation = Callable[[dict, str, random.Random, dict], bool]
"""(document, collection, rng, context) -> whether it applied; it edits the document in place."""


def _remove_required(doc: dict, collection: str, rng: random.Random, ctx: dict) -> bool:
    present = [k for k in ctx["required"][collection] if k in doc]
    if not present:
        return False
    del doc[rng.choice(present)]
    return True


def _add_note(doc: dict, collection: str, rng: random.Random, ctx: dict) -> bool:
    doc["note"] = "edited"
    return True


def _version_2(doc: dict, collection: str, rng: random.Random, ctx: dict) -> bool:
    doc["v"] = 2
    return True


def _outside_enum(doc: dict, collection: str, rng: random.Random, ctx: dict) -> bool:
    if collection == "transaction":
        doc["kind"] = "transfer"
    else:
        doc["status"] = "pending"
    return True


def _other_sku(doc: dict, collection: str, rng: random.Random, ctx: dict) -> bool:
    others = sorted(ctx["skus"] - {doc.get("sku")})
    if not others:
        return False
    doc["sku"] = rng.choice(others)
    return True


def _decimal_cents(doc: dict, collection: str, rng: random.Random, ctx: dict) -> bool:
    if not isinstance(doc.get("price"), dict) or "cents" not in doc["price"]:
        return False
    doc["price"]["cents"] = 12.5
    return True


def _other_type(doc: dict, collection: str, rng: random.Random, ctx: dict) -> bool:
    doc["type"] = "exception" if collection == "transaction" else "transaction"
    return True


def _bad_prev(doc: dict, collection: str, rng: random.Random, ctx: dict) -> bool:
    if collection != "transaction":
        return False
    doc["prev_txn"] = "txn::bad"
    return True


def _resolution_hlc(doc: dict, collection: str, rng: random.Random, ctx: dict) -> bool:
    res = doc.get("resolution")
    if collection != "exception" or not isinstance(res, dict) or not isinstance(res.get("hlc"), str):
        return False
    res["hlc"] = "-".join(res["hlc"].split("-")[:2]) + "-tablet-a"
    return True


def _check_out_to_customer(doc: dict, collection: str, rng: random.Random, ctx: dict) -> bool:
    if collection != "transaction" or doc.get("kind") != "check_out":
        return False
    doc["to_custodian"] = "customer"
    return True


MUTATIONS: tuple[Mutation, ...] = (_remove_required, _add_note, _version_2, _outside_enum, _other_sku,
                                   _decimal_cents, _other_type, _bad_prev, _resolution_hlc, _check_out_to_customer)


def required_keys(contracts: Path) -> dict[str, list[str]]:
    store = contracts / "schemas" / "store"
    return {c: json.loads((store / f"{c}.schema.json").read_text(encoding="utf-8"))["required"]
            for c in ("transaction", "exception")}


def _shuffled_with_duplicates(txns: list, res: list, rng: random.Random) -> tuple[list, list]:
    t, r = txns[:], res[:]
    t += rng.sample(txns, k=max(1, len(txns) // 3)) if txns else []
    r += r[:1]
    rng.shuffle(t)
    rng.shuffle(r)
    return t, r


def _corrupt(t: list, r: list, rng: random.Random, ctx: dict) -> None:
    docs = [(t, i, "transaction") for i in range(len(t))] + [(r, i, "exception") for i in range(len(r))]
    count = max(1, round(CORRUPT_SHARE * len(docs)))
    for target, i, collection in rng.sample(docs, k=min(count, len(docs))):
        doc = copy.deepcopy(target[i])
        applicable = list(MUTATIONS)
        while applicable:
            mutation = applicable.pop(rng.randrange(len(applicable)))
            if mutation(doc, collection, rng, ctx):
                break
        target[i] = doc


def make_sets(fixture: dict, seed: int, per_fixture: int, required: dict[str, list[str]]) -> list[tuple[str, dict]]:
    """The ``per_fixture`` sets of one fixture, as ``(file name, set)``."""
    name = fixture["name"]
    txns, res = copy.deepcopy(fixture["transactions"]), copy.deepcopy(fixture["resolutions"])
    skus = {d.get("sku") for d in txns + res if isinstance(d.get("sku"), str)}
    ctx = {"skus": skus, "required": required}
    out = []
    for k in range(per_fixture):
        rng = random.Random(f"{seed}/{name}/{k}")
        if k == 0:
            t, r = copy.deepcopy(txns), copy.deepcopy(res)
        elif k == 1:
            t, r = copy.deepcopy(txns[::-1]), copy.deepcopy(res[::-1])
        else:
            t, r = _shuffled_with_duplicates(copy.deepcopy(txns), copy.deepcopy(res), rng)
            if k >= per_fixture // 2:
                _corrupt(t, r, rng, ctx)
        out.append((f"{name}-{k}.json", {
            "name": name, "trip": fixture["trip"], "box": fixture["box"], "store": fixture["store"],
            "detector": fixture["expected"]["exceptions"]["detector"], "inventory": fixture["inventory"],
            "transactions": t, "resolutions": r,
        }))
    return out


def generate(seed: int, out: Path, per_fixture: int = DEFAULT_PER_FIXTURE, fixtures: Path | None = None,
             contracts: Path | None = None) -> list[Path]:
    fixtures = fixtures or default_fixtures_dir()
    required = required_keys(contracts or default_contracts_dir())
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for fixture in load_fixtures(fixtures):
        for file_name, doc_set in make_sets(fixture, seed, per_fixture, required):
            path = out / file_name
            path.write_text(json.dumps(doc_set, indent=1, ensure_ascii=True) + "\n", encoding="ascii")
            written.append(path)
    return written


def compare(a: dict, b: dict) -> list[str]:
    """One line per set, in file-name order: ``PASS <set>`` or ``FAIL <set>: <first difference>`` (A as expected)."""
    lines = []
    for name in sorted(set(a) | set(b)):
        if name not in b:
            lines.append(f"FAIL {name}: missing from B")
        elif name not in a:
            lines.append(f"FAIL {name}: missing from A")
        else:
            diff = first_difference(a[name], b[name], "report")
            lines.append(f"PASS {name}" if diff is None else f"FAIL {name}: {diff}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The ledger ports' differential test.")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="write the differential sets")
    gen.add_argument("--seed", type=int, required=True)
    gen.add_argument("--out", type=Path, required=True)
    gen.add_argument("--per-fixture", type=int, default=DEFAULT_PER_FIXTURE)
    gen.add_argument("--fixtures", type=Path, default=None, help="ledger fixture directory (default: the repository's)")
    cmp_ = sub.add_parser("compare", help="compare two reports set by set")
    cmp_.add_argument("a", type=Path)
    cmp_.add_argument("b", type=Path)
    args = parser.parse_args(argv)

    if args.command == "generate":
        if args.per_fixture < 1:
            parser.error("--per-fixture must be at least 1")
        written = generate(args.seed, args.out, args.per_fixture, args.fixtures)
        print(f"wrote {len(written)} sets to {args.out} (seed {args.seed})")
        return 0 if written else 1
    try:
        a, b = (json.loads(p.read_text(encoding="utf-8")) for p in (args.a, args.b))
    except (OSError, ValueError) as e:
        print(f"FAIL cannot read a report: {e}")
        return 1
    if not isinstance(a, dict) or not isinstance(b, dict):
        print("FAIL a report is one JSON object keyed by set file name")
        return 1
    lines = compare(a, b)
    for line in lines:
        print(line)
    if not lines:
        print("FAIL no sets in either report")
        return 1
    return 0 if all(line.startswith("PASS ") for line in lines) else 1


if __name__ == "__main__":
    sys.exit(main())
