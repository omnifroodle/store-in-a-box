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
    # The embedded code is the pairing page's drawing of that text, with the spec's 4-module quiet zone (#129).
    import qrcode
    import qrcode.image.svg

    def drawn(text, border):
        image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=border)
        return image.to_string(encoding="unicode")

    assert all(drawn(p, 4) in page for p in payloads)
    assert drawn(payloads[0], 2) not in page


def test_quiet_zone_is_four_modules():
    labels = load()
    svg = labels.qr_svg("JKT-RAIN-M-BLU#001")
    size = float(re.search(r'width="([\d.]+)mm"', svg).group(1))
    module = 1.2  # mm: box_size 12 at the generator's 0.1 mm per pixel
    modules = round(size / module)
    from qrcode import QRCode

    code = QRCode(border=0)
    code.add_data("JKT-RAIN-M-BLU#001")
    code.make(fit=True)
    assert modules == len(code.get_matrix()) + 2 * 4
    # The first dark module (the finder pattern's corner) sits four modules in from the edge.
    assert re.search(r'<path d="M4\.8,4\.8H', svg)


def test_default_is_five_per_sku(tmp_path):
    labels = load()
    out = tmp_path / "l.html"
    assert labels.main(["--out", str(out)]) == 0
    assert out.read_text().count('class="label"') == 5 * len(json.loads(SEED.read_text()))


def test_bad_seed_is_an_error(tmp_path):
    labels = load()
    assert labels.main(["--seed", str(tmp_path / "none.json"), "--out", str(tmp_path / "x.html")]) == 1
