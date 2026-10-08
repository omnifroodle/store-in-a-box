"""``conservation``: one row per SKU saying whether the ledger agrees with what the store released (CC5, #29).

Every unit in the ledger is in exactly one state, so a sum over the states is an identity, not a check. What ``holds``
checks: no unit the store never let go of (``untraced == 0``, both modes) and, with the store's inventory, no more
units than it had (``store_on_hand >= 0``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .chain import DISPUTED, HELD, SOLD, LedgerState


@dataclass(frozen=True)
class Row:
    sku: str
    opening_on_hand: int | None
    received: int | None
    left_store: int
    untraced: int
    returned_to_store: int
    store_on_hand: int | None
    in_custody: Mapping[str, int]
    sold: int
    disputed: int
    holds: bool

    def to_json(self) -> dict:
        return {
            "sku": self.sku,
            "opening_on_hand": self.opening_on_hand,
            "received": self.received,
            "left_store": self.left_store,
            "untraced": self.untraced,
            "returned_to_store": self.returned_to_store,
            "store_on_hand": self.store_on_hand,
            "in_custody": {c: self.in_custody[c] for c in sorted(self.in_custody)},
            "sold": self.sold,
            "disputed": self.disputed,
            "holds": self.holds,
        }


def conservation(state: LedgerState, store: str, inventory: Iterable[Mapping] | None) -> list[Row]:
    """Rows sorted by sku. ``inventory`` is the store's ``inventory`` documents (HQ side), or None at the venue.

    Venue rows cover the SKUs in the ledger and have null ``opening_on_hand``, ``received`` and ``store_on_hand``;
    with inventory the rows cover the SKUs in the ledger or the inventory (documents of other stores are ignored).
    """
    books: dict[str, Mapping] | None = None
    if inventory is not None:
        books = {doc["sku"]: doc for doc in sorted(inventory, key=lambda d: d.get("_id", "")) if doc["store"] == store}

    units_by_sku: dict[str, list[str]] = {}
    for unit_id, unit in state.units.items():
        units_by_sku.setdefault(unit.sku, []).append(unit_id)
    skus = set(units_by_sku) | (set(books) if books is not None else set())

    rows = []
    for sku in sorted(skus):
        unit_ids = units_by_sku.get(sku, [])
        untraced = sum(1 for u in unit_ids if u in state.untraced)
        left_store = len(unit_ids) - untraced
        returned = 0
        in_custody: Counter[str] = Counter()
        sold = disputed = 0
        for unit_id in unit_ids:
            unit = state.units[unit_id]
            if unit.state == SOLD:
                sold += 1
            elif unit.state == DISPUTED:
                disputed += 1
            elif unit.state == HELD and unit.holder == store:
                if unit_id not in state.untraced:
                    returned += 1
            elif unit.state == HELD:
                in_custody[unit.holder] += 1
        if books is None:
            opening = received = on_hand = None
            holds = untraced == 0
        else:
            doc = books.get(sku)
            opening = doc["opening_on_hand"] if doc else 0
            received = doc["received"] if doc else 0
            on_hand = opening + received - left_store + returned
            holds = untraced == 0 and on_hand >= 0
        rows.append(Row(sku=sku, opening_on_hand=opening, received=received, left_store=left_store, untraced=untraced,
                        returned_to_store=returned, store_on_hand=on_hand, in_custody=dict(in_custody), sold=sold,
                        disputed=disputed, holds=holds))
    return rows
