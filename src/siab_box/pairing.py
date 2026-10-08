"""The pairing payload each device scans (ports/box-agent.md), and the page that shows it as a QR."""

from __future__ import annotations

import hashlib
import html
import json
import ssl
from pathlib import Path

import qrcode
import qrcode.image.svg

PAYLOAD_VERSION = 1


def cert_sha256(cert_path: Path) -> str | None:
    """Lower-case hex sha256 of the DER form of Edge Server's certificate, or None when there is none."""
    try:
        pem = cert_path.read_text(encoding="ascii")
    except OSError:
        return None
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def payload(*, box: str, trip: str, device: str, edge_url: str, password: str, cert: str | None) -> dict:
    return {
        "v": PAYLOAD_VERSION,
        "box": box,
        "trip": trip,
        "device": device,
        "edge_url": edge_url,
        "user": device,
        "password": password,
        "cert_sha256": cert,
        "peer_group": f"siab-{trip}",
    }


def qr_svg(text: str) -> str:
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    return image.to_string(encoding="unicode")


def page(data: dict) -> str:
    text = json.dumps(data, separators=(",", ":"))
    device = html.escape(data["device"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pair {device}</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; background: #fff; color: #111; margin: 0 16px;
  text-align: center; }}
h1 {{ font-size: 2rem; margin: 1.5rem 0 .5rem; }}
.qr svg {{ width: min(80vw, 480px); height: auto; }}
p {{ color: #555; }}
</style></head>
<body>
<h1>Pair {device}</h1>
<p>{html.escape(data["box"])} &middot; {html.escape(data["trip"])} &middot; {html.escape(data["edge_url"])}</p>
<div class="qr">{qr_svg(text)}</div>
<p>Scan from the {device} app's pairing screen. This page carries the device's password and is served only on the
venue LAN; do not put it on a projector.</p>
<p><a href="/pair/{device}.json">payload as JSON</a> &middot; <a href="/">status</a></p>
</body></html>
"""
