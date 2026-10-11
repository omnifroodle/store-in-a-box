"""The runbook's stage beat is the ledger note's "On stage" text, and the acceptance list has one box per SPEC line."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTE = ROOT / "docs" / "architecture" / "conflict-free-ledger.md"
RUNBOOK = ROOT / "docs" / "runbook" / "phase0.md"
ACCEPTANCE = ROOT / "docs" / "runbook" / "phase0-acceptance.md"
SPEC = ROOT / "docs" / "SPEC.md"


def section(text: str, heading: str) -> str:
    """The body under the heading (any level), up to the next heading of any level."""
    match = re.search(rf"^#+ (?:[^\n]*: )?{re.escape(heading)}\n(.*?)(?=^#+ |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, heading
    return match.group(1).strip()


def test_stage_beat_is_the_note_text():
    assert section(RUNBOOK.read_text(), "Conflict-free by construction") == section(
        NOTE.read_text(), "Conflict-free by construction")


def test_one_checkbox_per_phase0_acceptance_line():
    spec = SPEC.read_text()
    phase0 = spec[spec.index("### Phase 0: Skeleton"):spec.index("### Phase 1:")]
    acceptance = phase0[phase0.index("**Acceptance.**"):]
    lines = [line for line in acceptance.splitlines() if line.startswith("- ")]
    boxes = re.findall(r"^- \[ \] \*\*\d\.", ACCEPTANCE.read_text(), re.MULTILINE)
    assert len(lines) == len(boxes) == 8
    assert all("Who:" in b for b in re.split(r"^- \[ \]", ACCEPTANCE.read_text(), flags=re.MULTILINE)[1:])
