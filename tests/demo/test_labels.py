"""scripts/demo/labels.py: one label per unit, each QR carrying exactly the payload the scanner parses."""

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "contracts" / "fixtures" / "seed" / "products.json"


def load():
    spec = importlib.util.spec_from_file_location("labels", ROOT / "scripts" / "demo" / "labels.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_labels_count_and_payloads(tmp_path):
    labels = load()
    out = tmp_path / "labels.html"
    assert labels.main(["--per-sku", "2", "--out", str(out)]) == 0
    page = out.read_text()
    skus = [p["sku"] for p in json.loads(SEED.read_text())]
    payloads = re.findall(r'<div class="label" data-payload="([^"]*)"', page)
    assert len(payloads) == 2 * len(skus)
    assert all(re.fullmatch(r"[A-Z0-9-]+#\d{3}", p) for p in payloads)
    assert payloads == [f"{s}#{n:03d}" for s in skus for n in (1, 2)]
    # The embedded code is the one the box's pairing page would draw for that exact text.
    from siab_box.pairing import qr_svg

    assert all(qr_svg(p) in page for p in payloads)


def test_default_is_five_per_sku(tmp_path):
    labels = load()
    out = tmp_path / "l.html"
    assert labels.main(["--out", str(out)]) == 0
    assert out.read_text().count('class="label"') == 5 * len(json.loads(SEED.read_text()))


def test_bad_seed_is_an_error(tmp_path):
    labels = load()
    assert labels.main(["--seed", str(tmp_path / "none.json"), "--out", str(tmp_path / "x.html")]) == 1
