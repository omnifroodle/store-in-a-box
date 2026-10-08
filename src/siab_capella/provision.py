"""`provision`: the `retail` bucket, its scopes, the Phase 0 collections and the indexes the HQ queries need."""

from __future__ import annotations

from functools import partial

from .gateway import CapellaGateway, Keyspace
from .plan import Step

BUCKET = "retail"
SCOPES = ("store", "agents", "ref")  # agents and ref stay empty until their phases
COLLECTIONS = ("product", "inventory", "trip", "allocation", "transaction", "exception")  # in scope store
INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "ix_txn_trip_unit": ("transaction", ("trip", "unit_id", "hlc")),
    "ix_txn_trip_hlc": ("transaction", ("trip", "hlc")),
    "ix_exc_trip_status": ("exception", ("trip", "status")),
    "ix_alloc_trip": ("allocation", ("trip", "custodian", "status")),
    "ix_inv_store": ("inventory", ("store", "sku")),
}


def ks(collection: str) -> Keyspace:
    return Keyspace(BUCKET, "store", collection)


def plan_provision(gw: CapellaGateway | None) -> list[Step]:
    """With no gateway (an offline dry run) every step is `ensure`: the plan, without the cluster's state."""

    def step(what: str, ensure, *args) -> Step:
        if gw is None:
            return Step("ensure", what)
        missing = ensure(*args, apply=False)
        return Step("create" if missing else "exists", what, partial(ensure, *args, apply=True))

    steps = [step(f"bucket {BUCKET}", gw and gw.ensure_bucket, BUCKET)]
    steps += [step(f"scope {BUCKET}.{s}", gw and gw.ensure_scope, BUCKET, s) for s in SCOPES]
    steps += [step(f"collection {ks(c)}", gw and gw.ensure_collection, ks(c)) for c in COLLECTIONS]
    for name, (coll, fields) in INDEXES.items():
        what = f"index {name} on {ks(coll)}({', '.join(fields)})"
        steps.append(step(what, gw and gw.ensure_index, name, ks(coll), fields))
    return steps
