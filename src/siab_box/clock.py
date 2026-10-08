"""The agent's one source of time, injected so tests run timers on virtual time."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def iso(stamp: datetime) -> str:
    """RFC 3339 in UTC, to the second, with a Z."""
    return stamp.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
