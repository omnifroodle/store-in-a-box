"""The uplink's two independent facts: is the App Services host reachable, and has the agent cut it."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from .clock import Clock, iso

Connect = Callable[[str, int], Awaitable[None]]

PROBE_INTERVAL = 5.0
PROBE_TIMEOUT = 2.0


class Uplink:
    def __init__(self, clock: Clock, target_host: str):
        self.clock = clock
        self.target_host = target_host
        self.reachable = False
        self.cut = False
        self.since = clock.now()

    def _changed(self) -> None:
        self.since = self.clock.now()

    def set_reachable(self, reachable: bool) -> None:
        if reachable != self.reachable:
            self.reachable = reachable
            self._changed()

    def set_cut(self, cut: bool) -> None:
        if cut != self.cut:
            self.cut = cut
            self._changed()

    def block(self) -> dict:
        return {"reachable": self.reachable, "cut": self.cut, "since": iso(self.since),
                "target_host": self.target_host}


async def tcp_connect(host: str, port: int) -> None:
    _, writer = await asyncio.open_connection(host, port)
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()


class UplinkProbe:
    """A TCP connect to the real host every `interval` seconds; no answer within `timeout` means unreachable.

    Both the interval and the timeout run on the injected clock, never on the event loop's own timers.
    """

    def __init__(self, uplink: Uplink, port: int, clock: Clock, connect: Connect = tcp_connect,
                 interval: float = PROBE_INTERVAL, timeout: float = PROBE_TIMEOUT):
        self.uplink = uplink
        self.port = port
        self.clock = clock
        self.connect = connect
        self.interval = interval
        self.timeout = timeout

    async def probe_once(self) -> bool:
        attempt = asyncio.ensure_future(self.connect(self.uplink.target_host, self.port))
        timer = asyncio.ensure_future(self.clock.sleep(self.timeout))
        try:
            await asyncio.wait({attempt, timer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (attempt, timer):
                task.cancel()
        if not attempt.done() or attempt.cancelled():
            return False
        return attempt.exception() is None

    async def run(self) -> None:
        while True:
            self.uplink.set_reachable(await self.probe_once())
            await self.clock.sleep(self.interval)
