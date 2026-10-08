"""ports/ledger.md names every operation and rule, and the fixed exception notes match the contract's table."""

from __future__ import annotations

import re
from pathlib import Path

from siab_ledger.exceptions import PROPOSED_RESOLUTION

REPO = Path(__file__).resolve().parents[2]


def test_port_doc_names_every_operation_and_rule():
    doc = (REPO / "ports" / "ledger.md").read_text(encoding="utf-8")
    for name in ("reduce(", "LedgerState", "exceptions_for(", "conservation(", "hlc_now(", "hlc_receive(",
                 "allocation_counts", "forks", "resolved_by", "untraced", "left_store", "returned_to_store",
                 "store_on_hand", "holds", "python -m siab_ledger check"):
        assert name in doc, name
    rules = re.findall(r"^(\d)\. \*\*", doc, re.MULTILINE)
    assert rules == [str(n) for n in range(1, 8)]
    assert "ledger.md" in (REPO / "ports" / "README.md").read_text(encoding="utf-8")


def test_fixed_notes_match_the_contract_table():
    readme = (REPO / "contracts" / "fixtures" / "README.md").read_text(encoding="utf-8")
    table = dict(re.findall(r"^\s*\| `(\w+)` \| `\w+` \| `([^`]+)` \|", readme, re.MULTILINE))
    assert set(table) == set(PROPOSED_RESOLUTION)
    for kind, note in table.items():
        assert PROPOSED_RESOLUTION[kind]["note"] == note
    actions = dict(re.findall(r"^\s*\| `(\w+)` \| `(\w+)` \|", readme, re.MULTILINE))
    assert {k: v["action"] for k, v in PROPOSED_RESOLUTION.items()} == actions
