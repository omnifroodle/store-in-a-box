"""scripts/ledger_diff.py: deterministic sets in the set format, a report per set, and a compare that names the
first difference."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from siab_ledger import ingest
from siab_ledger.__main__ import main as ledger_main
from siab_ledger.fixtures import canonical, first_difference

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "contracts" / "fixtures" / "ledger"
FIXTURES = sorted(p.stem for p in LEDGER.glob("*.json"))


def load_script():
    spec = importlib.util.spec_from_file_location("ledger_diff", ROOT / "scripts" / "ledger_diff.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def diff():
    return load_script()


@pytest.fixture(scope="module")
def generated(diff, tmp_path_factory):
    """Seed 7, the default six sets per fixture, and its Python report."""
    out = tmp_path_factory.mktemp("diff")
    diff.generate(7, out / "sets")
    assert ledger_main(["report", "--sets", str(out / "sets"), "--out", str(out / "r.json")]) == 0
    return out


def _files(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.glob("*.json"))}


def test_generate_is_deterministic_per_seed(diff, generated, tmp_path):
    diff.generate(7, tmp_path / "again")
    assert _files(tmp_path / "again") == _files(generated / "sets")
    diff.generate(8, tmp_path / "other")
    assert _files(tmp_path / "other") != _files(generated / "sets")
    assert set(_files(tmp_path / "other")) == set(_files(generated / "sets"))


def test_every_set_validates_against_the_set_format(diff, generated):
    Draft202012Validator.check_schema(diff.SET_SCHEMA)
    validator = Draft202012Validator(diff.SET_SCHEMA)
    names = sorted(p.name for p in (generated / "sets").glob("*.json"))
    assert names == sorted(f"{f}-{k}.json" for f in FIXTURES for k in range(6))
    for p in (generated / "sets").glob("*.json"):
        doc_set = json.loads(p.read_text())
        assert list(validator.iter_errors(doc_set)) == [], p.name
        assert p.name.startswith(doc_set["name"] + "-")


def test_the_kinds_of_set(diff, generated):
    fx = json.loads((LEDGER / "double-scan.json").read_text())
    sets = {k: json.loads((generated / "sets" / f"double-scan-{k}.json").read_text()) for k in range(6)}
    assert sets[0]["transactions"] == fx["transactions"] and sets[0]["detector"] == "tablet-a"
    assert sets[1]["transactions"] == fx["transactions"][::-1]
    assert len(sets[2]["transactions"]) == len(fx["transactions"]) + 1  # a third delivered twice
    assert ingest(sets[2]["transactions"], "transaction").drops == []
    for k in (3, 4, 5):  # corrupted: at least one document dropped
        assert ingest(sets[k]["transactions"], "transaction").drops or ingest(
            sets[k]["resolutions"], "exception").drops, k


def test_uncorrupted_sets_reproduce_the_fixtures(generated):
    report = json.loads((generated / "r.json").read_text())
    for name in FIXTURES:
        fx = json.loads((LEDGER / f"{name}.json").read_text())
        ks = (0, 1, 2) if fx["order_independent"] else (0,)
        for k in ks:
            assert first_difference(fx["expected"], report[f"{name}-{k}.json"]) is None, (name, k)


def test_corruptions_reach_every_code_a_mutation_can_give(generated):
    report = json.loads((generated / "r.json").read_text())
    codes = Counter(d["code"] for result in report.values() for d in result["drops"])
    assert set(codes) == {"wrong_type", "version", "missing_field", "extra_field", "invalid_value", "rule"}


def test_report_is_canonical_json(generated):
    text = (generated / "r.json").read_text(encoding="ascii")
    assert text == canonical(json.loads(text))
    assert list(json.loads(text)) == sorted(json.loads(text))


def test_compare_passes_a_report_with_itself_and_fails_on_a_difference(diff, generated, tmp_path, capsys):
    r = generated / "r.json"
    assert diff.main(["compare", str(r), str(r)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 6 * len(FIXTURES) and all(line.startswith("PASS ") for line in lines)

    other = json.loads(r.read_text())
    other["double-scan-0.json"]["units"]["JKT-RAIN-M-BLU#001"]["holder"] = "box-07"
    other["drop-newer-version-3.json"]["drops"] = []
    del other["pack-and-sell-5.json"]
    (tmp_path / "b.json").write_text(canonical(other))
    assert diff.main(["compare", str(r), str(tmp_path / "b.json")]) == 1
    out = capsys.readouterr().out.splitlines()
    fails = [line for line in out if line.startswith("FAIL ")]
    assert fails[0] == 'FAIL double-scan-0.json: report.units.JKT-RAIN-M-BLU#001.holder: got "box-07", expected null'
    assert fails[1].startswith("FAIL drop-newer-version-3.json: report.drops: 0 items, expected ")
    assert fails[2] == "FAIL pack-and-sell-5.json: missing from B"
    assert len(fails) == 3


def test_compare_refuses_unreadable_or_empty_reports(diff, tmp_path, capsys):
    (tmp_path / "empty.json").write_text("{}")
    (tmp_path / "list.json").write_text("[]")
    assert diff.main(["compare", str(tmp_path / "empty.json"), str(tmp_path / "empty.json")]) == 1
    assert diff.main(["compare", str(tmp_path / "list.json"), str(tmp_path / "empty.json")]) == 1
    assert diff.main(["compare", str(tmp_path / "missing.json"), str(tmp_path / "empty.json")]) == 1
    assert all(line.startswith("FAIL ") for line in capsys.readouterr().out.splitlines())


def test_cli_generate(diff, tmp_path, capsys):
    assert diff.main(["generate", "--seed", "3", "--out", str(tmp_path / "s"), "--per-fixture", "2"]) == 0
    assert capsys.readouterr().out == f"wrote {2 * len(FIXTURES)} sets to {tmp_path / 's'} (seed 3)\n"
    with pytest.raises(SystemExit):
        diff.main(["generate", "--seed", "3", "--out", str(tmp_path / "s"), "--per-fixture", "0"])


def test_the_mac_script_runs_the_three_steps():
    script = (ROOT / "scripts" / "ledger_diff.sh").read_text()
    for step in ("ledger_diff.py generate", "siab_ledger report", "LedgerDifferentialTests", "SIAB_DIFF_SETS",
                 "SIAB_DIFF_OUT", "ledger_diff.py compare"):
        assert step in script, step
