import json

import pytest

from siab_capella.config import SEED_DIR
from siab_capella.gateway import Keyspace
from siab_capella.seed import differences, load_seed, plan_seed

PRODUCT = Keyspace("retail", "store", "product")
TRIP = Keyspace("retail", "store", "trip")


def test_load_seed_reads_every_fixture_and_drops_fixture_only_keys():
    docs = load_seed(SEED_DIR)
    by_coll = {}
    for ks, doc_id, body in docs:
        by_coll.setdefault(ks.collection, []).append(doc_id)
        assert not any(k.startswith("_") for k in body)
        assert body["type"] == ks.collection
    for coll, name in (("product", "products.json"), ("inventory", "inventory.json"), ("trip", "trips.json")):
        want = [d["_id"] for d in json.loads((SEED_DIR / name).read_text())]
        assert by_coll[coll] == want


def test_seed_writes_once_then_plans_nothing(cli, fake):
    code, out = cli("seed", "--yes")
    assert code == 0
    assert len([c for c in fake.calls if c[0] == "upsert"]) == len(load_seed(SEED_DIR))
    assert fake.get(TRIP, "trip::trip-2026-10-18-riverfest")["venue"]["name"] == "Richmond Riverfest"
    calls = len(fake.calls)
    code, out = cli("seed", "--yes")
    assert code == 0 and "nothing to do" in out and len(fake.calls) == calls


def test_seed_diff_reports_live_edit(cli, fake):
    cli("seed", "--yes")
    code, out = cli("seed", "--diff")
    assert code == 0
    assert out.strip().endswith("0 differences")

    live = fake.get(PRODUCT, "product::JKT-RAIN-M-BLU")
    live["price"]["cents"] = 9900  # an edit made in the Capella UI
    live["note"] = "on sale"
    fake.upsert(PRODUCT, "product::JKT-RAIN-M-BLU", live)
    del fake.docs[TRIP]["trip::trip-2026-10-18-riverfest"]
    calls = len(fake.calls)

    code, out = cli("seed", "--diff", "--yes")  # --diff never writes, even with --yes
    assert code == 0
    assert "retail.store.product product::JKT-RAIN-M-BLU: differs" in out
    assert "price.cents: 9900 -> 12900" in out
    assert 'note: "on sale" -> (absent)' in out
    assert "retail.store.trip trip::trip-2026-10-18-riverfest: missing from the cluster" in out
    assert out.strip().endswith("2 differences")
    assert len(fake.calls) == calls


def test_seed_plan_shows_the_overwrite_before_applying(cli, fake):
    cli("seed", "--yes")
    live = fake.get(PRODUCT, "product::SOC-WOOL-M")
    live["tags"] = ["wool", "clearance"]
    fake.upsert(PRODUCT, "product::SOC-WOOL-M", live)
    code, out = cli("seed")
    assert "seed: 1 change(s)" in out
    assert "update    retail.store.product product::SOC-WOOL-M" in out
    assert 'tags: ["wool", "clearance"] -> ["wool"]' in out
    assert fake.get(PRODUCT, "product::SOC-WOOL-M")["tags"] == ["wool", "clearance"]


def test_seed_diff_needs_the_cluster(cli):
    code, out = cli("seed", "--diff", env={}, gateway=None)
    assert code == 1
    assert "not set" in out


def test_seed_trip_filter(fake):
    docs = load_seed(SEED_DIR, "trip-2026-10-18-riverfest")
    assert [d for _, d, _ in docs if d.startswith("trip::")] == ["trip::trip-2026-10-18-riverfest"]
    with pytest.raises(ValueError, match="not in"):
        load_seed(SEED_DIR, "trip-1999-01-01-nowhere")


def test_seed_unknown_trip_is_an_error(cli, fake):
    code, out = cli("seed", "--trip", "trip-1999-01-01-nowhere", "--yes")
    assert code == 1 and "not in" in out and fake.calls == []


def test_seed_uses_siab_trip_by_default(cli):
    code, out = cli("seed", env={"SIAB_TRIP": "trip-1999-01-01-nowhere"})
    assert code == 1 and "trip-1999-01-01-nowhere" in out


def test_differences():
    assert differences({"a": 1, "b": {"c": [1]}}, {"a": 1, "b": {"c": [1]}}) == []
    assert differences({"b": {"c": [1]}}, {"b": {"c": [1, 2]}}) == ["b.c: [1] -> [1, 2]"]
    assert differences({}, {"x": None}) == ["x: (absent) -> null"]


def test_plan_seed_offline_writes_nothing():
    steps = plan_seed(None, load_seed(SEED_DIR))
    assert {s.action for s in steps} == {"ensure"} and all(s.run is None for s in steps)
