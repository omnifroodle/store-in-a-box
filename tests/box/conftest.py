"""Fakes for the box tests: a virtual clock, a fake App Services upstream, and a Box wired to both."""

from __future__ import annotations

import asyncio
import heapq
import itertools
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from siab_box import agent
from siab_box.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]

ENV = {
    "APP_SERVICES_PUBLIC_URL": "wss://app.example.test:4984/store",
    "BOX_APP_USER": "box-07",
    "BOX_APP_PASSWORD": "box-secret",
    "SIAB_TRIP": "trip-2026-10-18-riverfest",
    "SIAB_REGION": "va-central",
    "EDGE_TABLET_A_PASSWORD": "pw-a",
    "EDGE_TABLET_B_PASSWORD": "pw-b",
    "EDGE_PHONE_1_PASSWORD": "pw-phone",
}


async def settle(rounds: int = 30) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


class FakeClock:
    """Virtual time: sleep() waits until advance() moves the clock past its deadline."""

    def __init__(self, start: datetime = datetime(2026, 10, 18, 14, 0, tzinfo=UTC)):
        self.start = start
        self.t = 0.0
        self._sleepers: list = []
        self._seq = itertools.count()

    def now(self) -> datetime:
        return self.start + timedelta(seconds=self.t)

    async def sleep(self, seconds: float) -> None:
        fut = asyncio.get_running_loop().create_future()
        heapq.heappush(self._sleepers, (self.t + seconds, next(self._seq), fut))
        await fut

    async def advance(self, seconds: float) -> None:
        end = self.t + seconds
        await settle()
        while self._sleepers and self._sleepers[0][0] <= end:
            deadline, _, fut = heapq.heappop(self._sleepers)
            self.t = max(self.t, deadline)
            if not fut.done():
                fut.set_result(None)
            await settle()
        self.t = end
        await settle()


class FakeAppServices:
    """Plays the App Services end of the uplink: answers the WebSocket handshake, then echoes every byte."""

    RESPONSE = (b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n")

    def __init__(self, handshake: bool = True):
        self.handshake = handshake
        self.heads: list[bytes] = []
        self.connections = 0
        self.server: asyncio.Server | None = None
        self.port = 0

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            if self.handshake:
                self.heads.append(await reader.readuntil(b"\r\n\r\n"))
                writer.write(self.RESPONSE)
                await writer.drain()
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def start(self) -> FakeAppServices:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        assert self.server is not None
        self.server.close()


def settings(env: dict | None = None, **overrides) -> Settings:
    return Settings.from_env({**ENV, **(env or {})}, **overrides)


def make_box(clock: FakeClock, edge_handler=None, env: dict | None = None, **overrides):
    """A Box over a mocked Edge Server; the proxy's upstream is redirected by the caller when it needs one."""
    handler = edge_handler or (lambda request: httpx.Response(503))
    client = httpx.AsyncClient(base_url="http://edge.test", transport=httpx.MockTransport(handler))
    return agent.build_box(settings(env, **overrides), client, "192.0.2.10", clock)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def kit():
    """The helpers above, for test modules (pytest's importlib mode does not put conftest on sys.path)."""
    import types

    return types.SimpleNamespace(ENV=dict(ENV), FIXTURES=FIXTURES, REPO=REPO, settle=settle, settings=settings,
                                 make_box=make_box, FakeAppServices=FakeAppServices)
