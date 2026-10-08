"""The contract validator passes its self-test and finds no problem in the contracts on this branch."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_validator():
    spec = importlib.util.spec_from_file_location("check_contracts", ROOT / "scripts" / "check_contracts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_self_test_passes():
    load_validator().self_test()


def test_contracts_have_no_problems():
    assert load_validator().run(ROOT / "contracts") == []


def test_an_edited_fixture_is_caught(tmp_path):
    import shutil

    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    seed = tmp_path / "contracts" / "fixtures" / "seed" / "products.json"
    seed.write_text(seed.read_text().replace('"cents": 12900', '"cents": 129.5', 1))
    problems = load_validator().run(tmp_path / "contracts")
    assert any("products.json" in p and "cents" in p for p in problems), problems
