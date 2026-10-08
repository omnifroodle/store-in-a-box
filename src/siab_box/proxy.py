"""The counting proxy: the box's software uplink.

Edge Server's replication to App Services connects here (loopback only). Two ways in, one count:

- WebSocket: the replication target is `ws://127.0.0.1:<proxy port>/<endpoint>`; the proxy opens the real connection
  (TLS for `wss://`), rewrites the `Host` header of the handshake and relays.
- CONNECT: the replication's `proxy` setting points here and Edge Server tunnels its own TLS through; the proxy only
  allows the App Services host and port.

Bytes are counted on the upstream socket only: `out` is what the box sent to App Services, `in` what it received.
"""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from collections.abc import Awaitable, Callable

from .clock import Clock, iso
from .settings import Target
from .uplink import Uplink

Streams = tuple[asyncio.StreamReader, asyncio.StreamWriter]
OpenUpstream = Callable[[str, int, bool], Awaitable[Streams]]

HEAD_LIMIT = 64 * 1024
CHUNK = 64 * 1024
UPSTREAM_CONNECT_TIMEOUT = 15.0


class ByteCounter:
    def __init__(self, clock: Clock, source: str = "proxy"):
        self.clock = clock
        self.source = source
        self.inbound = 0
        self.outbound = 0
        self.since = clock.now()

    def reset(self) -> None:
        self.inbound = 0
        self.outbound = 0
        self.since = self.clock.now()

    def block(self) -> dict:
        return {"in": self.inbound, "out": self.outbound, "since": iso(self.since), "source": self.source}


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover - certifi comes with httpx
        return ssl.create_default_context()


async def open_upstream(host: str, port: int, tls: bool) -> Streams:
    ctx = _ssl_context() if tls else None
    return await asyncio.wait_for(
        asyncio.open_connection(host, port, ssl=ctx, server_hostname=host if tls else None),
        UPSTREAM_CONNECT_TIMEOUT,
    )


def rewrite_host(head: bytes, authority: str) -> bytes:
    """The request head with its Host header replaced by the App Services authority."""
    lines = head.split(b"\r\n")
    out = [lines[0]]
    for line in lines[1:]:
        if line.lower().startswith(b"host:"):
            out.append(b"Host: " + authority.encode("ascii"))
        else:
            out.append(line)
    return b"\r\n".join(out)


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()


class CountingProxy:
    def __init__(self, target: Target, counter: ByteCounter, uplink: Uplink,
                 open_upstream: OpenUpstream = open_upstream):
        self.target = target
        self.counter = counter
        self.uplink = uplink
        self.open_upstream = open_upstream
        self._live: set[asyncio.StreamWriter] = set()

    # ---------------------------------------------------------------- cut and restore

    def cut(self) -> None:
        """Refuse new connections and close every relayed one; bytes are left alone."""
        self.uplink.set_cut(True)
        for writer in list(self._live):
            writer.close()
        self._live.clear()

    def restore(self) -> None:
        self.uplink.set_cut(False)

    # ---------------------------------------------------------------- the connection

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.uplink.cut:
            await _close(writer)
            return
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            await _close(writer)
            return
        method, _, rest = head.partition(b" ")
        authority = rest.partition(b" ")[0].decode("latin-1")
        try:
            if method == b"CONNECT":
                if authority != f"{self.target.host}:{self.target.port}":
                    writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                    await _close(writer)
                    return
                up_reader, up_writer = await self.open_upstream(self.target.host, self.target.port, False)
            else:
                up_reader, up_writer = await self.open_upstream(self.target.host, self.target.port, self.target.tls)
        except (OSError, TimeoutError):
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await _close(writer)
            return
        if self.uplink.cut:  # cut while the upstream was connecting
            await _close(up_writer)
            await _close(writer)
            return
        self._live.update((writer, up_writer))
        try:
            if method == b"CONNECT":
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
            else:
                await self._send(up_writer, rewrite_host(head, self.target.authority), outbound=True)
            await asyncio.gather(
                self._pump(reader, up_writer, outbound=True),
                self._pump(up_reader, writer, outbound=False),
            )
        except (ConnectionError, OSError):
            pass
        finally:
            self._live.discard(writer)
            self._live.discard(up_writer)
            await _close(up_writer)
            await _close(writer)

    async def _send(self, dst: asyncio.StreamWriter, data: bytes, outbound: bool) -> bool:
        if self.uplink.cut or dst.is_closing():
            return False
        dst.write(data)
        if outbound:
            self.counter.outbound += len(data)
        else:
            self.counter.inbound += len(data)
        await dst.drain()
        return True

    async def _pump(self, src: asyncio.StreamReader, dst: asyncio.StreamWriter, outbound: bool) -> None:
        try:
            while True:
                data = await src.read(CHUNK)
                if not data or not await self._send(dst, data, outbound):
                    break
        except (ConnectionError, OSError):
            pass
        finally:
            # one side ending ends the pair, so the other pump's read returns
            dst.close()

    async def serve(self, host: str, port: int) -> asyncio.Server:
        return await asyncio.start_server(self.handle, host, port, limit=HEAD_LIMIT)
