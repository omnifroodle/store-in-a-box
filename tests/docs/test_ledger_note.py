"""docs/architecture/conflict-free-ledger.md keeps the blueprint's sections and quotes the fixtures it walks exactly."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTE = ROOT / "docs" / "architecture" / "conflict-free-ledger.md"

SECTIONS = [
    "The pattern in one paragraph",
    "Why not a conflict resolver",
    "The documents",
    "The reducer",
    "Worked example",
    "The same reducer on every node",
    "What it costs",
    "On stage: Conflict-free by construction",
    "Talking points",
    "Possible enhancements",
    "Alternatives and trade-offs",
    "Related",
]


def test_note_has_the_sections_in_order():
    headings = re.findall(r"^## (.+)$", NOTE.read_text(), re.MULTILINE)
    assert headings == SECTIONS


def test_where_it_lives_table_has_the_blueprint_columns():
    assert "| Artifact | Path | Checked by |" in NOTE.read_text()


def test_walked_exceptions_are_quoted_as_the_fixtures_expect():
    note = NOTE.read_text()
    for name in ("double-scan", "oversell-hq"):
        fixture = json.loads((ROOT / "contracts" / "fixtures" / "ledger" / f"{name}.json").read_text())
        assert f"contracts/fixtures/ledger/{name}.json" in note
        for doc in fixture["expected"]["exceptions"]["docs"]:
            assert doc["_id"] in note
            assert doc["dispute_key"] in note
            assert f"`{doc['kind']}`" in note
            assert doc["proposed_resolution"]["note"] in note
            assert "|".join(doc["transactions"]) in note  # the string the hash is taken over


def test_stage_sentence_is_the_d8_wording():
    sentence = ("Two sales of the last unit are not a conflict. They are a fork in one unit's history, and the fork "
                "is the exception, with both sales attached.")
    assert sentence in " ".join(NOTE.read_text().split())
