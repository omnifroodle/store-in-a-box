"""The counting proxy against a fake App Services upstream on loopback (no network beyond 127.0.0.1)."""

from __future__ import annotations

import asyncio

from siab_box import status
from siab_box.proxy import rewrite_host

HANDSHAKE = (b"GET /store/_blipsync HTTP/1.1\r\nHost: 127.0.0.1:8790\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n"
             b"Sec-WebSocket-Protocol: BLIP_3+CBMobile_3\r\nAuthorization: Basic Ym94LTA3OmJveC1zZWNyZXQ=\r\n\r\n")
PAYLOAD = bytes(range(256)) * 37  # 9472 bytes, every byte value


async def _rig(clock, kit):
    """A Box whose proxy reaches the fake upstream, and the proxy listening on an ephemeral loopback port."""
    upstream = await kit.FakeAppServices().start()
    box = kit.make_box(clock)
    calls = []

    async def open_upstream(host, port, tls):
        calls.append((host, port, tls))
        return await asyncio.open_connection("127.0.0.1", upstream.port)

    box.proxy.open_upstream = open_upstream
    server = await box.proxy.serve("127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return box, upstream, server, port, calls


async def _handshake(port):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(HANDSHAKE)
    await writer.drain()
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    return reader, writer, head


async def _closed(reader) -> bool:
    """The peer closed: EOF, or a reset when the closed side had unread bytes (both are a failed connection)."""
    try:
        return await asyncio.wait_for(reader.read(), 5) == b""
    except ConnectionResetError:
        return True


async def _echo(reader, writer, data):
    writer.write(data)
    await writer.drain()
    return await asyncio.wait_for(reader.readexactly(len(data)), 5)


def test_proxy_counts_bytes_exactly(clock, kit):
    async def main():
        box, upstream, server, port, calls = await _rig(clock, kit)
        reader, writer, head = await _handshake(port)
        assert head == kit.FakeAppServices.RESPONSE
        assert await _echo(reader, writer, PAYLOAD) == PAYLOAD
        await kit.settle()

        # the upstream saw the handshake with its own Host, over TLS because the URL is wss://
        assert calls == [("app.example.test", 4984, True)]
        sent_head = upstream.heads[0]
        assert b"Host: app.example.test:4984\r\n" in sent_head and b"127.0.0.1:8790" not in sent_head
        assert sent_head == rewrite_host(HANDSHAKE, "app.example.test:4984")
        assert box.counter.outbound == len(sent_head) + len(PAYLOAD)
        assert box.counter.inbound == len(kit.FakeAppServices.RESPONSE) + len(PAYLOAD)
        writer.close()
        server.close()
        await upstream.stop()

    asyncio.run(main())


def test_host_rewrite_keeps_every_other_header():
    head = b"GET /x HTTP/1.1\r\nhost: a:1\r\nX-Other: host: b\r\n\r\n"
    want = b"GET /x HTTP/1.1\r\nHost: app.example.test\r\nX-Other: host: b\r\n\r\n"
    assert rewrite_host(head, "app.example.test") == want


def test_uplink_cut_drops_relay_and_restore_resumes(clock, kit):
    async def main():
        box, upstream, server, port, calls = await _rig(clock, kit)
        reader, writer, _ = await _handshake(port)
        await _echo(reader, writer, b"before the cut")
        since = box.counter.block()["since"]

        await clock.advance(30)
        code, _, body = status.route(box, "POST", "/uplink/cut")
        assert code == 200 and b'"cut": true' in body
        # the relayed connection is closed under the replicator
        assert await _closed(reader)
        writer.close()
        before = (box.counter.inbound, box.counter.outbound)

        # a new connection is accepted and closed at once; the upstream is never dialled
        r2, w2 = await asyncio.open_connection("127.0.0.1", port)
        w2.write(HANDSHAKE)
        assert await _closed(r2)
        w2.close()
        await kit.settle()
        assert len(calls) == 1
        assert (box.counter.inbound, box.counter.outbound) == before

        # cut twice is still cut
        assert status.route(box, "POST", "/uplink/cut")[0] == 200 and box.uplink.cut

        await clock.advance(30)
        code, _, body = status.route(box, "POST", "/uplink/restore")
        assert code == 200 and b'"cut": false' in body
        reader, writer, _ = await _handshake(port)
        assert await _echo(reader, writer, PAYLOAD) == PAYLOAD
        assert box.counter.inbound > before[0] and box.counter.outbound > before[1]
        assert box.counter.block()["since"] == since  # neither cut nor restore touches bytes
        writer.close()
        server.close()
        await upstream.stop()

    asyncio.run(main())


def test_connect_tunnel_relays_only_to_app_services(clock, kit):
    async def main():
        upstream = await kit.FakeAppServices(handshake=False).start()
        box = kit.make_box(clock)
        calls = []

        async def open_upstream(host, port, tls):
            calls.append((host, port, tls))
            return await asyncio.open_connection("127.0.0.1", upstream.port)

        box.proxy.open_upstream = open_upstream
        server = await box.proxy.serve("127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"CONNECT elsewhere.example.test:443 HTTP/1.1\r\nHost: elsewhere.example.test:443\r\n\r\n")
        assert (await reader.read()).startswith(b"HTTP/1.1 403")
        assert calls == []
        writer.close()

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"CONNECT app.example.test:4984 HTTP/1.1\r\nHost: app.example.test:4984\r\n\r\n")
        assert await reader.readuntil(b"\r\n\r\n") == b"HTTP/1.1 200 Connection established\r\n\r\n"
        assert await _echo(reader, writer, PAYLOAD) == PAYLOAD
        # Edge Server's own TLS goes through untouched: the proxy does not add TLS, and counts only the tunnel
        assert calls == [("app.example.test", 4984, False)]
        assert box.counter.inbound == box.counter.outbound == len(PAYLOAD)
        writer.close()
        server.close()
        await upstream.stop()

    asyncio.run(main())


def test_unreachable_upstream_answers_502(clock, kit):
    async def main():
        box = kit.make_box(clock)

        async def refuse(host, port, tls):
            raise ConnectionRefusedError

        box.proxy.open_upstream = refuse
        server = await box.proxy.serve("127.0.0.1", 0)
        reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        writer.write(HANDSHAKE)
        assert (await asyncio.wait_for(reader.read(), 5)).startswith(b"HTTP/1.1 502")
        assert box.counter.inbound == box.counter.outbound == 0
        writer.close()
        server.close()

    asyncio.run(main())
