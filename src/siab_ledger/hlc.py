"""Hybrid logical clock (HLC) helpers.

An HLC is the string ``<unix_ms:13 digits>-<counter:4 hex>-<device_id>`` (``contracts/schemas/common.schema.json``,
``$defs/hlc``). The fields are fixed width, so comparing two HLC strings lexicographically is comparing them in
causal order, with the device id breaking ties between writers.

The clock is injected: ``clock`` is any callable returning the current unix time in milliseconds, so tests drive it
with a fake clock and never read the wall clock.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

Clock = Callable[[], int]
"""Returns the current unix time in milliseconds."""

HLC_PATTERN = re.compile(r"^([0-9]{13})-([0-9a-f]{4})-([a-z][a-z0-9-]*)$")
DEVICE_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
MAX_MS = 10**13 - 1
MAX_COUNTER = 0xFFFF


@dataclass(frozen=True, order=True)
class Hlc:
    """A parsed HLC. Ordering the dataclass orders by (ms, counter, device), the same as the string."""

    ms: int
    counter: int
    device: str

    def __str__(self) -> str:
        return format_hlc(self.ms, self.counter, self.device)


def format_hlc(ms: int, counter: int, device: str) -> str:
    if not 0 <= ms <= MAX_MS:
        raise ValueError(f"hlc milliseconds out of range: {ms}")
    if not 0 <= counter <= MAX_COUNTER:
        raise ValueError(f"hlc counter out of range: {counter}")
    if not DEVICE_PATTERN.match(device):
        raise ValueError(f"not a device id: {device!r}")
    return f"{ms:013d}-{counter:04x}-{device}"


def parse_hlc(value: str) -> Hlc:
    match = HLC_PATTERN.match(value)
    if match is None:
        raise ValueError(f"not an hlc: {value!r}")
    return Hlc(int(match.group(1)), int(match.group(2), 16), match.group(3))


def compare_hlc(a: str, b: str) -> int:
    """-1, 0 or 1 as ``a`` is before, equal to or after ``b`` (lexicographic, which is causal order)."""
    parse_hlc(a)
    parse_hlc(b)
    return (a > b) - (a < b)


def _advance(ms: int, counter: int) -> tuple[int, int]:
    """The next (ms, counter) after the given one: a full counter carries into the milliseconds."""
    if counter < MAX_COUNTER:
        return ms, counter + 1
    return ms + 1, 0


def _device(last: str | None, device: str | None) -> str:
    if device is not None:
        return device
    if last is None:
        raise ValueError("a device id is needed when there is no previous hlc")
    return parse_hlc(last).device


def hlc_now(clock: Clock, last: str | None, device: str | None = None) -> str:
    """The HLC for a local event (writing a document).

    ``last`` is the last HLC this device issued or received (None on a fresh device); ``device`` defaults to the device
    of ``last``. The result is strictly greater than ``last`` whatever the clock does, and follows the clock when it
    moves ahead.
    """
    dev = _device(last, device)
    pt = clock()
    if last is None:
        return format_hlc(pt, 0, dev)
    prev = parse_hlc(last)
    if pt > prev.ms:
        return format_hlc(pt, 0, dev)
    return format_hlc(*_advance(prev.ms, prev.counter), dev)


def hlc_receive(local_last: str | None, remote: str, clock: Clock, device: str | None = None) -> str:
    """Merge a remote HLC on receive; the result is strictly greater than both ``local_last`` and ``remote``.

    ``device`` defaults to the device of ``local_last``; the remote writer's device never becomes ours.
    """
    dev = _device(local_last, device)
    r = parse_hlc(remote)
    pt = clock()
    if local_last is None:
        l_ms, l_c = -1, 0
    else:
        mine = parse_hlc(local_last)
        l_ms, l_c = mine.ms, mine.counter
    ms = max(l_ms, r.ms, pt)
    if ms == l_ms and ms == r.ms:
        result = _advance(ms, max(l_c, r.counter))
    elif ms == l_ms:
        result = _advance(ms, l_c)
    elif ms == r.ms:
        result = _advance(ms, r.counter)
    else:
        result = (ms, 0)
    return format_hlc(*result, dev)
