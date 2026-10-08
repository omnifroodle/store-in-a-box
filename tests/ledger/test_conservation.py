"""conservation: holds is a check that can fail (CC5), venue-side and HQ-side."""

from __future__ import annotations

from pathlib import Path

import pytest

from siab_ledger import conservation, reduce

LEDGER_FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "ledger"
FIXTURE_NAMES = [p.stem for p in sorted(LEDGER_FIXTURES.glob("*.json"))]


def rows(fx, inventory):
    state = reduce(fx["transactions"], fx["resolutions"], store=fx["store"])
    return {r.sku: r for r in conservation(state, fx["store"], inventory)}


def test_conservation_holds_can_fail(fixture):
    over = fixture("overpacked")
    venue = rows(over, None)["HAT-BRIM-OS"]
    assert venue.holds is True
    assert venue.store_on_hand is None and venue.opening_on_hand is None and venue.received is None
    hq = rows(over, over["inventory"])["HAT-BRIM-OS"]
    assert hq.store_on_hand == -1
    assert hq.holds is False

    untraced = fixture("untraced-unit")
    for inventory in (None, untraced["inventory"]):
        row = rows(untraced, inventory)["SOC-WOOL-M"]
        assert row.untraced == 1
        assert row.holds is False

    day = fixture("conservation-day")
    assert all(r.holds for r in rows(day, day["inventory"]).values())
    assert all(r.holds for r in rows(day, None).values())


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_identity_holds_by_construction(name, fixture):
    fx = fixture(name)
    for inventory in (None, fx["inventory"]):
        for row in rows(fx, inventory).values():
            assert row.left_store + row.untraced == (
                row.returned_to_store + sum(row.in_custody.values()) + row.sold + row.disputed)


def test_inventory_only_sku_and_other_stores(fixture):
    fx = fixture("pack-and-sell")
    inventory = [
        {"_id": "inventory::store-richmond::SOC-WOOL-M", "v": 1, "type": "inventory", "store": "store-richmond",
         "sku": "SOC-WOOL-M", "opening_on_hand": 10, "received": 2, "as_of": "2026-10-17T00:00:00Z"},
        {"_id": "inventory::store-norfolk::JKT-RAIN-M-BLU", "v": 1, "type": "inventory", "store": "store-norfolk",
         "sku": "JKT-RAIN-M-BLU", "opening_on_hand": 99, "received": 0, "as_of": "2026-10-17T00:00:00Z"},
    ]
    got = rows(fx, inventory)
    assert list(got) == ["JKT-RAIN-M-BLU", "SOC-WOOL-M"]
    shell = got["JKT-RAIN-M-BLU"]  # no inventory for this store: opening 0, so three packed overdraw it
    assert (shell.opening_on_hand, shell.received, shell.store_on_hand, shell.holds) == (0, 0, -3, False)
    socks = got["SOC-WOOL-M"]
    assert (socks.left_store, socks.store_on_hand, socks.holds) == (0, 12, True)
    assert list(rows(fx, None)) == ["JKT-RAIN-M-BLU"]


def test_returned_to_store(fixture):
    day = fixture("conservation-day")
    shell = rows(day, day["inventory"])["JKT-RAIN-M-BLU"]
    assert (shell.left_store, shell.returned_to_store, shell.store_on_hand) == (8, 1, 5)
