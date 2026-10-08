"""`seed`: products, inventory and trips from contracts/fixtures/seed/. A re-seed overwrites a live edit (FOREMAN.md),
so `--diff` shows live-versus-fixture differences first and writes nothing."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

from .gateway import CapellaGateway, Keyspace
from .plan import Step
from .provision import ks

SEED_FILES = {"product": "products.json", "inventory": "inventory.json", "trip": "trips.json"}

SeedDoc = tuple[Keyspace, str, dict[str, Any]]


def load_seed(seed_dir: Path, trip: str | None = None) -> list[SeedDoc]:
    """The seed documents as (keyspace, id, body); the body drops the fixture-only keys (`_id`, `_why`). With
    `trip`, only that trip is seeded (products and inventory always are)."""
    out: list[SeedDoc] = []
    for collection, name in SEED_FILES.items():
        for doc in json.loads((seed_dir / name).read_text(encoding="utf-8")):
            if collection == "trip" and trip and doc["trip_id"] != trip:
                continue
            out.append((ks(collection), doc["_id"], {k: v for k, v in doc.items() if not k.startswith("_")}))
    if trip and not any(k.collection == "trip" for k, _, _ in out):
        raise ValueError(f"trip {trip} is not in {seed_dir / SEED_FILES['trip']}")
    return out


def differences(live: Any, want: Any, path: str = "") -> list[str]:
    """Field-level differences, one line each: `path: live -> fixture`. Lists compare whole."""
    if isinstance(live, dict) and isinstance(want, dict):
        out: list[str] = []
        for k in sorted(set(live) | set(want)):
            sub = f"{path}.{k}" if path else k
            if k not in want:
                out.append(f"{sub}: {json.dumps(live[k])} -> (absent)")
            elif k not in live:
                out.append(f"{sub}: (absent) -> {json.dumps(want[k])}")
            else:
                out += differences(live[k], want[k], sub)
        return out
    return [] if live == want else [f"{path or '(document)'}: {json.dumps(live)} -> {json.dumps(want)}"]


def plan_seed(gw: CapellaGateway | None, docs: list[SeedDoc]) -> list[Step]:
    steps: list[Step] = []
    for keyspace, doc_id, body in docs:
        what = f"{keyspace} {doc_id}"
        if gw is None:
            steps.append(Step("ensure", what))
            continue
        run = partial(gw.upsert, keyspace, doc_id, body)
        live = gw.get(keyspace, doc_id)
        if live is None:
            steps.append(Step("create", what, run))
        elif diff := differences(live, body):
            steps.append(Step("update", what, run, diff))
        else:
            steps.append(Step("unchanged", what))
    return steps


RESET_COLLECTIONS = ("allocation", "transaction", "exception")


def plan_reset_trip(gw: CapellaGateway | None, trip: str) -> list[Step]:
    """Delete a trip's venue documents before a rehearsal. The deletes go through the SDK; App Services imports them
    as tombstones, which reach the devices through the old documents' channels (the sync functions route them)."""
    steps: list[Step] = []
    for c in RESET_COLLECTIONS:
        keyspace = ks(c)
        if gw is None:
            steps.append(Step("ensure", f"{keyspace}: delete every document of {trip}"))
            continue
        ids = gw.query(f"SELECT RAW META(d).id FROM {keyspace.sqlpp()} AS d WHERE d.`trip` = $trip", {"trip": trip})
        steps += [Step("delete", f"{keyspace} {i}", partial(gw.delete, keyspace, i)) for i in ids]
        if not ids:
            steps.append(Step("unchanged", f"{keyspace}: no documents of {trip}"))
    return steps
