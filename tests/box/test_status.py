"""The agent's HTTP API: status, reset, the two independent uplink facts, pairing and the certificate."""

from __future__ import annotations

import asyncio
import json
import shutil

from siab_box import status


def _get(box, path, method="GET"):
    code, ctype, body = status.route(box, method, path)
    return code, ctype, (json.loads(body) if ctype == "application/json" else body.decode())


def test_reset_zeroes_and_restamps(clock, kit):
    async def main():
        box = kit.make_box(clock)
        box.counter.inbound, box.counter.outbound = 1234, 567
        await clock.advance(90)
        code, _, body = _get(box, "/bytes/reset", "POST")
        assert code == 200
        assert body == {"bytes": {"in": 0, "out": 0, "since": "2026-10-18T14:01:30Z"}}
        assert _get(box, "/status")[2]["bytes"] == {"in": 0, "out": 0, "since": "2026-10-18T14:01:30Z",
                                                    "source": "proxy"}

    asyncio.run(main())


def test_status_reports_cut_and_reachable_independently(clock, kit):
    box = kit.make_box(clock)
    box.uplink.set_reachable(True)

    # the WAN cable is pulled: unreachable, not cut
    box.uplink.set_reachable(False)
    uplink = _get(box, "/status")[2]["uplink"]
    assert (uplink["reachable"], uplink["cut"]) == (False, False)

    # cable back, then the software cut: reachable and cut
    box.uplink.set_reachable(True)
    assert _get(box, "/uplink/cut", "POST")[2]["uplink"]["cut"] is True
    uplink = _get(box, "/status")[2]["uplink"]
    assert (uplink["reachable"], uplink["cut"]) == (True, True)
    assert uplink["target_host"] == "app.example.test"

    # both at once
    box.uplink.set_reachable(False)
    uplink = _get(box, "/status")[2]["uplink"]
    assert (uplink["reachable"], uplink["cut"]) == (False, True)

    assert _get(box, "/uplink/restore", "POST")[2]["uplink"] == {**uplink, "cut": False,
                                                                 "since": uplink["since"]}


def test_status_top_level(clock, kit):
    box = kit.make_box(clock)
    body = _get(box, "/status")[2]
    assert body["box"] == "box-07" and body["trip"] == "trip-2026-10-18-riverfest"
    assert body["edge_server"] == {"up": False, "version": None, "url": "ws://192.0.2.10:59840/retail"}
    assert body["replication"]["state"] == "unknown"
    assert body["pairing"] == ["tablet-a", "tablet-b", "phone-1"]


def test_pairing_pages(clock, kit):
    box = kit.make_box(clock)
    code, _, data = _get(box, "/pair/tablet-b.json")
    assert code == 200
    assert data["device"] == data["user"] == "tablet-b" and data["password"] == "pw-b"
    assert data["cert_sha256"] is None and data["peer_group"] == "siab-trip-2026-10-18-riverfest"
    code, ctype, page = _get(box, "/pair/phone-1")
    assert code == 200 and ctype.startswith("text/html") and "<svg" in page and "LAN" in page
    assert _get(box, "/pair/tablet-z")[0] == 404
    assert _get(box, "/pair/tablet-z.json")[0] == 404


def test_cert_only_with_tls(clock, kit, tmp_path):
    box = kit.make_box(clock)
    assert _get(box, "/cert.pem")[0] == 404

    shutil.copy(kit.FIXTURES / "test-cert.pem", tmp_path / "cert.pem")
    box = kit.make_box(clock, env={"EDGE_TLS": "on", "EDGE_PORT": "59999"}, edge_dir=tmp_path)
    code, ctype, pem = _get(box, "/cert.pem")
    assert code == 200 and pem.startswith("-----BEGIN CERTIFICATE-----")
    data = _get(box, "/pair/tablet-a.json")[2]
    assert data["edge_url"] == "wss://192.0.2.10:59999/retail"
    # openssl x509 -in tests/box/fixtures/test-cert.pem -outform der | shasum -a 256
    assert data["cert_sha256"] == "4b7fea9b4a88769b79fefa2626f30dbb35e7a80db1fa0e869ae06a37a2182ce8"


def test_status_page_is_one_html_file(clock, kit):
    code, ctype, page = _get(kit.make_box(clock), "/")
    assert code == 200 and ctype.startswith("text/html")
    assert 'fetch("/status"' in page and "2000" in page and "UPLINK CUT" in page
    assert "<script src" not in page and "<link" not in page  # no build step, no framework


def test_unknown_routes(clock, kit):
    box = kit.make_box(clock)
    assert _get(box, "/nope")[0] == 404
    assert _get(box, "/status", "POST")[0] == 404
    assert _get(box, "/status", "DELETE")[0] == 405


def test_over_http(clock, kit):
    async def main():
        box = kit.make_box(clock)
        server = await status.serve(box, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"POST /uplink/cut HTTP/1.1\r\nHost: box\r\nContent-Length: 0\r\n\r\n")
        raw = await asyncio.wait_for(reader.read(), 5)
        head, _, body = raw.partition(b"\r\n\r\n")
        assert head.startswith(b"HTTP/1.1 200 OK") and b"Content-Type: application/json" in head
        assert json.loads(body)["uplink"]["cut"] is True
        writer.close()
        server.close()

    asyncio.run(main())
