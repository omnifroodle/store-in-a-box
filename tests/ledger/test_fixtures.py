"""Every golden fixture passes, in its own order and in any other; the CLI reports it in the fixed format."""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pytest

from siab_ledger import ingest, reduce
from siab_ledger.__main__ import main
from siab_ledger.fixtures import canonical, check, first_difference, run

LEDGER_FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "ledger"
FIXTURE_NAMES = [p.stem for p in sorted(LEDGER_FIXTURES.glob("*.json"))]  # file-name order, as the CLI prints


def test_there_are_fixtures():
    assert len(FIXTURE_NAMES) >= 21


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_passes(name, fixture):
    fx = fixture(name)
    assert first_difference(fx["expected"], run(fx)) is None
    assert check(fx, seed=0).difference is None


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_exception_documents_are_byte_identical_to_the_fixture(name, fixture):
    fx = fixture(name)
    got = run(fx)["exceptions"]["docs"]
    assert json.dumps(got) == json.dumps(fx["expected"]["exceptions"]["docs"])


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fork_detection_is_order_independent(name, fixture):
    fx = fixture(name)
    if not fx["order_independent"]:
        pytest.skip("fixture is not marked order_independent")
    store = fx["store"]

    def reduced(txns, res):  # rule 0 first: the reducer's input is what ingest accepts
        t_in, r_in = ingest(txns, "transaction"), ingest(res, "exception")
        return reduce(t_in.accepted, r_in.accepted, store=store), t_in.drops + r_in.drops

    baseline = reduced(fx["transactions"], fx["resolutions"])
    rng = random.Random(f"order/{name}")
    for _ in range(40):
        txns = list(fx["transactions"])
        txns += rng.sample(txns, k=rng.randint(0, len(txns)))  # duplicates by id collapse
        res = list(fx["resolutions"]) * rng.randint(1, 2)
        rng.shuffle(txns)
        rng.shuffle(res)
        assert reduced(txns, res) == baseline
    assert first_difference(fx["expected"], run(fx)) is None


def test_cli_passes_every_fixture(capsys):
    assert main(["check"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [f"PASS {name}" for name in FIXTURE_NAMES]


def test_cli_seed_and_directory(capsys, tmp_path):
    shutil.copy(LEDGER_FIXTURES / "double-scan.json", tmp_path / "double-scan.json")
    assert main(["check", "--fixtures", str(tmp_path), "--seed", "42"]) == 0
    assert capsys.readouterr().out == "PASS double-scan\n"


def test_cli_reports_the_first_difference_and_exits_1(capsys, tmp_path):
    fx = json.loads((LEDGER_FIXTURES / "pack-and-sell.json").read_text())
    fx["expected"]["units"]["JKT-RAIN-M-BLU#002"]["holder"] = "box-07"
    (tmp_path / "pack-and-sell.json").write_text(json.dumps(fx))
    shutil.copy(LEDGER_FIXTURES / "double-scan.json", tmp_path / "double-scan.json")
    assert main(["check", "--fixtures", str(tmp_path)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "PASS double-scan"
    assert out[1] == ('FAIL pack-and-sell: expected.units.JKT-RAIN-M-BLU#002.holder: got "customer", '
                      'expected "box-07"')


def test_cli_with_no_fixtures_fails(capsys, tmp_path):
    assert main(["check", "--fixtures", str(tmp_path)]) == 1
    assert capsys.readouterr().out.startswith("FAIL no fixtures")


def test_shuffled_reruns_catch_an_order_dependent_build(fixture, monkeypatch):
    """A reducer whose answer depends on arrival order passes the fixture as written but fails a re-run."""
    import siab_ledger.fixtures as runner

    real_reduce = runner.reduce

    def first_seen_wins(transactions, resolutions=(), *, store):
        txns = list(transactions)
        state = real_reduce(txns, resolutions, store=store)
        if txns and txns[0]["_id"] != fixture("pack-and-sell")["transactions"][0]["_id"]:
            return real_reduce(txns[1:], resolutions, store=store)
        return state

    monkeypatch.setattr(runner, "reduce", first_seen_wins)
    outcome = check(fixture("pack-and-sell"), seed=0)
    assert outcome.difference is not None
    assert outcome.line.startswith("FAIL pack-and-sell: ")


def test_first_difference_reports_list_lengths_and_types():
    assert first_difference([1, 2], [1]) == "expected: 1 items, expected 2"
    assert first_difference({"a": 1}, {"a": True}) == "expected.a: got true, expected 1"
    assert first_difference({"a": 1}, {}) == "expected.a: missing"
    assert first_difference({}, {"b": None}) == "expected.b: unexpected null"


DROP_FIXTURES = [n for n in FIXTURE_NAMES if n.startswith("drop-")]


def test_the_eight_drop_fixtures_are_there():
    assert len(DROP_FIXTURES) == 8 and len(FIXTURE_NAMES) == 47


@pytest.mark.parametrize("name", DROP_FIXTURES)
@pytest.mark.parametrize("seed", [0, 1, 20261013])
def test_drop_fixtures_give_the_same_drops_in_every_ordering(name, seed, fixture):
    from siab_ledger.fixtures import orderings

    fx = fixture(name)
    assert fx["expected"]["drops"]
    for label, txns, res in orderings(fx, seed):
        assert first_difference(fx["expected"], run(fx, txns, res)) is None, label


def test_a_missed_drop_is_a_difference(fixture):
    fx = fixture("drop-newer-version")
    fx["expected"]["drops"] = []
    assert check(fx).line.startswith("FAIL drop-newer-version: expected.drops: 1 items, expected 0")


def test_report_over_sets_is_canonical(tmp_path, capsys):
    for name in ("double-scan", "drop-extra-field-same-id"):
        fx = json.loads((LEDGER_FIXTURES / f"{name}.json").read_text())
        detector = fx["expected"]["exceptions"]["detector"]
        for key in ("expected", "description", "order_independent"):
            del fx[key]
        (tmp_path / "sets").mkdir(exist_ok=True)
        (tmp_path / "sets" / f"{name}-0.json").write_text(json.dumps({**fx, "detector": detector}))
    out = tmp_path / "r.json"
    assert main(["report", "--sets", str(tmp_path / "sets"), "--out", str(out)]) == 0
    assert capsys.readouterr().out == f"wrote 2 sets to {out}\n"
    text = out.read_text(encoding="ascii")
    got = json.loads(text)
    assert text == canonical(got) and ": " not in text and ", " not in text
    assert list(got) == ["double-scan-0.json", "drop-extra-field-same-id-0.json"]
    for name in ("double-scan", "drop-extra-field-same-id"):
        fx = json.loads((LEDGER_FIXTURES / f"{name}.json").read_text())
        assert first_difference(fx["expected"], got[f"{name}-0.json"]) is None
    assert main(["report", "--sets", str(tmp_path / "none"), "--out", str(out)]) == 1
