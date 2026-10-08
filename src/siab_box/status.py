"""The agent's HTTP API and status page (ports/box-agent.md). Plain asyncio, one request per connection."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from . import pairing
from .edge import EdgeMonitor
from .proxy import ByteCounter, CountingProxy
from .uplink import Uplink


@dataclass
class Box:
    """Everything /status reports, in one place."""

    box_id: str
    trip: str
    edge_url: str
    edge_tls: bool
    cert_path: Path
    device_passwords: dict[str, str]
    counter: ByteCounter
    uplink: Uplink
    proxy: CountingProxy
    edge: EdgeMonitor
    devices: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.devices = list(self.device_passwords)

    def status(self) -> dict:
        return {
            "box": self.box_id,
            "trip": self.trip,
            "edge_server": {"up": self.edge.up, "version": self.edge.version, "url": self.edge_url},
            "uplink": self.uplink.block(),
            "replication": self.edge.replication_block(),
            "bytes": self.counter.block(),
            "pairing": list(self.devices),
        }

    def pairing_payload(self, device: str) -> dict:
        cert = pairing.cert_sha256(self.cert_path) if self.edge_tls else None
        return pairing.payload(box=self.box_id, trip=self.trip, device=device, edge_url=self.edge_url,
                               password=self.device_passwords[device], cert=cert)


Response = tuple[int, str, bytes]

REASONS = {200: "OK", 404: "Not Found", 405: "Method Not Allowed", 400: "Bad Request"}


def _json(body: dict, status: int = 200) -> Response:
    return status, "application/json", json.dumps(body).encode()


def _not_found() -> Response:
    return _json({"error": "not found"}, 404)


def status_page() -> bytes:
    return resources.files("siab_box").joinpath("status.html").read_bytes()


def route(box: Box, method: str, path: str) -> Response:
    path = path.split("?", 1)[0]
    if method == "GET":
        if path == "/status":
            return _json(box.status())
        if path == "/":
            return 200, "text/html; charset=utf-8", status_page()
        if path == "/cert.pem":
            if not box.edge_tls:
                return _not_found()
            try:
                return 200, "application/x-pem-file", box.cert_path.read_bytes()
            except OSError:
                return _not_found()
        if path.startswith("/pair/"):
            name = path[len("/pair/"):]
            as_json = name.endswith(".json")
            device = name[: -len(".json")] if as_json else name
            if device not in box.device_passwords:
                return _not_found()
            data = box.pairing_payload(device)
            if as_json:
                return _json(data)
            return 200, "text/html; charset=utf-8", pairing.page(data).encode()
        return _not_found()
    if method == "POST":
        if path == "/uplink/cut":
            box.proxy.cut()
            return _json({"uplink": box.uplink.block()})
        if path == "/uplink/restore":
            box.proxy.restore()
            return _json({"uplink": box.uplink.block()})
        if path == "/bytes/reset":
            box.counter.reset()
            block = box.counter.block()
            return _json({"bytes": {"in": block["in"], "out": block["out"], "since": block["since"]}})
        return _not_found()
    return _json({"error": "method not allowed"}, 405)


async def handle(box: Box, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        head = await reader.readuntil(b"\r\n\r\n")
        request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = request_line.split(" ")
        if len(parts) != 3:
            status, ctype, body = _json({"error": "bad request"}, 400)
        else:
            status, ctype, body = route(box, parts[0].upper(), parts[1])
        writer.write(
            f"HTTP/1.1 {status} {REASONS.get(status, '')}\r\nContent-Type: {ctype}\r\n"
            f"Content-Length: {len(body)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n".encode()
            + body)
        await writer.drain()
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        pass
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def serve(box: Box, host: str, port: int) -> asyncio.Server:
    return await asyncio.start_server(lambda r, w: handle(box, r, w), host, port, limit=16 * 1024)
