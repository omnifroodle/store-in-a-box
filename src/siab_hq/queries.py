"""What the HQ reads from Capella, and the fake that answers the same statements from a ledger fixture.

Every read goes through WS2's ``CapellaGateway`` (``ports/capella.md``). The SQL++ is fixed in shape by the blueprint
(``docs/workstreams/WS5-hq.md``, "Interfaces"); each statement also selects ``META().id AS _id``, because the ledger
(``siab_ledger``) keys documents by their id. ``GET /api/conservation?sql=1`` returns these statements as run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from siab_capella.gateway import CapellaGateway, FakeCapella
from siab_capella.provision import ks

TRANSACTIONS = (f"SELECT META(t).id AS _id, t.* FROM {ks('transaction').sqlpp()} AS t "
                "WHERE t.trip = $trip ORDER BY t.hlc")
EXCEPTIONS = f"SELECT META(e).id AS _id, e.* FROM {ks('exception').sqlpp()} AS e WHERE e.trip = $trip"
INVENTORY = f"SELECT META(i).id AS _id, i.* FROM {ks('inventory').sqlpp()} AS i WHERE i.store = $store"
ALLOCATIONS = f"SELECT META(a).id AS _id, a.* FROM {ks('allocation').sqlpp()} AS a WHERE a.trip = $trip"


class TripNotFound(LookupError):
    pass


@dataclass(frozen=True)
class TripData:
    """One read of a trip: the documents the reducer, the conservation rows and the tree are computed from."""

    trip: str
    store: str
    trip_doc: dict
    transactions: list[dict]
    exceptions: list[dict]
    inventory: list[dict]
    allocations: list[dict]
    statements: list[dict] = field(default_factory=list)


def statements(trip: str, store: str) -> list[dict]:
    """The statements one read runs, with their parameters, for ``?sql=1``."""
    return [
        {"statement": TRANSACTIONS, "params": {"trip": trip}},
        {"statement": EXCEPTIONS, "params": {"trip": trip}},
        {"statement": INVENTORY, "params": {"store": store}},
        {"statement": ALLOCATIONS, "params": {"trip": trip}},
    ]


def trip_doc(gw: CapellaGateway, trip: str) -> dict:
    doc = gw.get(ks("trip"), f"trip::{trip}")
    if doc is None:
        raise TripNotFound(f"trip::{trip} is not in {ks('trip')}")
    return doc


def load(gw: CapellaGateway, trip: str) -> TripData:
    """Read the trip, its transactions, exceptions and allocations, and its store's inventory."""
    doc = trip_doc(gw, trip)
    store = doc["store"]
    stmts = statements(trip, store)
    txns, excs, inv, allocs = (gw.query(s["statement"], s["params"]) for s in stmts)
    return TripData(trip=trip, store=store, trip_doc=doc, transactions=txns, exceptions=excs, inventory=inv,
                    allocations=allocs, statements=stmts)


def body(doc: dict) -> dict:
    """A document as stored: the fixture-only keys (``_id``, ``_why``) dropped."""
    return {k: v for k, v in doc.items() if not k.startswith("_")}


# ---------------------------------------------------------------- the fake (unit tests and SIAB_HQ_FAKE)

_FIELD = {TRANSACTIONS: ("transaction", "trip"), EXCEPTIONS: ("exception", "trip"),
          INVENTORY: ("inventory", "store"), ALLOCATIONS: ("allocation", "trip")}


def fake_query_handler(fake: FakeCapella):
    """A ``FakeCapella.query_handler`` that answers the statements above (and the ids-by-field shape WS2's
    ``FakeCapella`` understands itself) from the fake's documents."""

    def handler(statement: str, params: dict[str, Any]) -> list[Any]:
        if statement not in _FIELD:
            fake.query_handler = None
            try:
                return fake.query(statement, params)
            finally:
                fake.query_handler = handler
        collection, name = _FIELD[statement]
        docs = fake.docs.get(ks(collection), {})
        rows = [{"_id": i, **d} for i, d in sorted(docs.items()) if d.get(name) == params[name]]
        if statement == TRANSACTIONS:
            rows.sort(key=lambda r: (r["hlc"], r["_id"]))
        return rows

    return handler


def seed_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


def fake_from_fixture(fixture: dict, *, fixtures: Path | None = None) -> FakeCapella:
    """A ``FakeCapella`` holding a ledger fixture: its transactions, its resolutions (as exception documents) and its
    inventory, plus the seed's trip document and products. Its ``query_handler`` answers this module's statements."""
    root = fixtures or seed_dir()
    fake = FakeCapella()
    for c in ("product", "inventory", "trip", "allocation", "transaction", "exception"):
        fake.docs.setdefault(ks(c), {})
    seed = root / "seed"
    for name, collection in (("trips.json", "trip"), ("products.json", "product")):
        for doc in json.loads((seed / name).read_text(encoding="utf-8")):
            fake.docs[ks(collection)][doc["_id"]] = body(doc)
    for collection, docs in (("transaction", fixture["transactions"]), ("exception", fixture["resolutions"]),
                             ("inventory", fixture["inventory"] or [])):
        for doc in docs:
            fake.docs[ks(collection)][doc["_id"]] = body(doc)
    fake.query_handler = fake_query_handler(fake)
    return fake


def fixture_path(name_or_path: str, *, fixtures: Path | None = None) -> Path:
    """``oversell-hq`` (a name in ``contracts/fixtures/ledger/``) or a path to a ledger fixture file."""
    if re.fullmatch(r"[a-z0-9-]+", name_or_path):
        return (fixtures or seed_dir()) / "ledger" / f"{name_or_path}.json"
    return Path(name_or_path)


def fake_gateway(name_or_path: str) -> tuple[FakeCapella, dict]:
    """The gateway ``SIAB_HQ_FAKE`` selects, and the fixture it was loaded from."""
    fixture = json.loads(fixture_path(name_or_path).read_text(encoding="utf-8"))
    return fake_from_fixture(fixture), fixture
