#!/usr/bin/env python3
"""Print-ready unit labels: one per unit `<SKU>#<serial>`, the QR holding exactly the payload the tablet's scanner
parses (app/StoreInABox/UI/Scanner/ScanParser.swift).

    uv run python scripts/demo/labels.py [--seed PRODUCTS.json] [--per-sku N] [--out labels.html]

Open the HTML in a browser and print it at 100% scale on Avery 5160-style stock (30-up, 2 5/8 x 1 inch). The layout
is the CSS in this file.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED = ROOT / "contracts" / "fixtures" / "seed" / "products.json"
DEFAULT_PER_SKU = 5  # D3 (#8)
PAYLOAD = re.compile(r"^[A-Z0-9-]+#\d{3}$")

CSS = """
@page { size: letter; margin: 0.5in 0.19in; }
body { margin: 0; font-family: -apple-system, Helvetica, Arial, sans-serif; }
.sheet { display: grid; grid-template-columns: repeat(3, 2.625in); column-gap: 0.125in; }
.label { box-sizing: border-box; height: 1in; padding: 0.06in 0.1in; display: flex; align-items: center; gap: 0.1in;
  overflow: hidden; break-inside: avoid; }
.qr { flex: none; width: 0.85in; height: 0.85in; }
.qr svg { width: 100%; height: 100%; }
.text { min-width: 0; line-height: 1.15; }
.sku { font: 700 9pt ui-monospace, Menlo, monospace; overflow-wrap: anywhere; }
.serial { font-size: 14pt; font-weight: 700; }
.name { font-size: 8pt; }
"""


def unit_ids(skus: Sequence[str], per_sku: int) -> list[str]:
    return [f"{sku}#{serial:03d}" for sku in skus for serial in range(1, per_sku + 1)]


# The QR spec's quiet zone. siab_box.pairing.qr_svg draws 2: enough for a screen, thin on a 0.85 in label.
QUIET_ZONE_MODULES = 4


def qr_svg(text: str) -> str:
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=QUIET_ZONE_MODULES)
    return image.to_string(encoding="unicode")


def label(unit: str, name: str) -> str:
    sku, _, serial = unit.partition("#")
    return (f'<div class="label" data-payload="{html.escape(unit)}"><div class="qr">{qr_svg(unit)}</div>'
            f'<div class="text"><div class="sku">{html.escape(sku)}</div><div class="serial">#{serial}</div>'
            f'<div class="name">{html.escape(name)}</div></div></div>')


def render(products: Sequence[dict], per_sku: int) -> str:
    names = {p["sku"]: p["name"] for p in products}
    units = unit_ids(list(names), per_sku)
    bad = [u for u in units if not PAYLOAD.match(u)]
    if bad:
        raise ValueError(f"SKU(s) the scanner would refuse: {', '.join(bad[:3])}")
    body = "\n".join(label(u, names[u.partition("#")[0]]) for u in units)
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Store in a Box unit labels</title>'
            f'<style>{CSS}</style><body><div class="sheet">\n{body}\n</div></body></html>\n')


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="the seed products (default: the contract fixture)")
    p.add_argument("--per-sku", type=int, default=DEFAULT_PER_SKU, help="units per SKU, serials 001..N (default 5)")
    p.add_argument("--out", type=Path, default=Path("labels.html"))
    args = p.parse_args(argv)
    if not 1 <= args.per_sku <= 999:
        p.error("--per-sku is 1..999 (the serial is three digits)")
    try:
        products = json.loads(args.seed.read_text())
        page = render(products, args.per_sku)
    except (OSError, ValueError, KeyError) as e:
        print(f"labels.py: {e}", file=sys.stderr)
        return 1
    args.out.write_text(page)
    print(f"wrote {len(products) * args.per_sku} labels to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
