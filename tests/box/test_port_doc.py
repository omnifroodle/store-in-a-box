"""ports/box-agent.md is the contract WS4, WS5 and WS7 read: the agent's JSON must match its examples exactly."""

from __future__ import annotations

import json
import re

from siab_box import status
from siab_box.settings import DEVICES


def _doc(kit) -> str:
    return (kit.REPO / "ports" / "box-agent.md").read_text(encoding="utf-8")


def _example(doc: str, heading: str) -> dict:
    """The first ```json block after the heading line that contains `heading`."""
    start = next(m.end() for m in re.finditer(r"^#+ .*$", doc, re.MULTILINE) if heading in m.group(0))
    block = re.search(r"```json\n(.*?)```", doc[start:], re.DOTALL)
    return json.loads(block.group(1))


def shape(value):
    """Keys in order and value types, recursively; null is its own type."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__


def _live_box(clock, kit):
    box = kit.make_box(clock)
    box.edge.up, box.edge.version, box.edge.state = True, "1.1.0", "idle"
    box.uplink.set_reachable(True)
    return box


def test_status_json_shape(clock, kit):
    body = json.loads(status.route(_live_box(clock, kit), "GET", "/status")[2])
    example = _example(_doc(kit), "GET /status")
    assert shape(body) == shape(example)
    assert body["pairing"] == example["pairing"]


def test_pairing_payload_matches_port_doc(clock, kit):
    payload = json.loads(status.route(_live_box(clock, kit), "GET", "/pair/tablet-a.json")[2])
    example = _example(_doc(kit), "Pairing payload")
    assert list(payload) == list(example)  # fields exactly, in order
    assert shape(payload) == shape(example)
    for field in ("v", "box", "trip", "device", "user", "peer_group"):
        assert payload[field] == example[field], field


def test_cut_restore_and_reset_bodies_match_port_doc(clock, kit):
    doc = _doc(kit)
    box = _live_box(clock, kit)
    assert shape(json.loads(status.route(box, "POST", "/uplink/cut")[2])) == shape(_example(doc, "/uplink/cut"))
    assert shape(json.loads(status.route(box, "POST", "/bytes/reset")[2])) == shape(_example(doc, "/bytes/reset"))


def test_devices_match_the_custodian_registry(kit):
    custodians = json.loads((kit.REPO / "contracts" / "fixtures" / "seed" / "custodians.json").read_text())
    devices = [c["edge_user"] for c in custodians if c["kind"] == "device" and c["box"] == "box-07"]
    assert list(DEVICES) == devices
    box = next(c for c in custodians if c["id"] == "box-07")
    assert box["channels"] == ["trip:trip-2026-10-18-riverfest", "catalog:va-central", "box:box-07"]
