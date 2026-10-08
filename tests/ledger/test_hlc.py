"""HLC helpers under a fake clock: monotonic, merge on receive, lexicographic order is causal order."""

from __future__ import annotations

import pytest

from siab_ledger import Hlc, compare_hlc, format_hlc, hlc_now, hlc_receive, parse_hlc


def test_format_and_parse_round_trip():
    value = format_hlc(1792328410000, 0x1A, "tablet-a")
    assert value == "1792328410000-001a-tablet-a"
    assert parse_hlc(value) == Hlc(1792328410000, 0x1A, "tablet-a")
    assert str(parse_hlc(value)) == value
    for bad in ("1792328410000-001A-tablet-a", "179232841000-0000-tablet-a", "1792328410000-0000-Tablet", ""):
        with pytest.raises(ValueError):
            parse_hlc(bad)
    with pytest.raises(ValueError):
        format_hlc(1, 0x10000, "tablet-a")


def test_hlc_monotonic_under_fake_clock(clock):
    issued = [hlc_now(clock, None, "tablet-a")]
    assert issued[0] == "1792328400000-0000-tablet-a"
    for step in (0, 0, 5, -10_000, 0, 1, -1, 20_000):  # stalls, steps forward, jumps backward
        clock.advance(step)
        issued.append(hlc_now(clock, issued[-1]))
    assert issued == sorted(issued)
    assert len(set(issued)) == len(issued)
    assert all(parse_hlc(h).device == "tablet-a" for h in issued)
    assert issued[1] == "1792328400000-0001-tablet-a"  # same millisecond: the counter moves
    assert issued[-1] == "1792328410005-0000-tablet-a"  # the clock is ahead again: counter resets


def test_counter_overflow_carries_into_the_milliseconds(clock):
    last = format_hlc(clock(), 0xFFFF, "tablet-a")
    nxt = hlc_now(clock, last)
    assert nxt == format_hlc(clock() + 1, 0, "tablet-a")
    assert nxt > last


def test_hlc_receive_is_after_both(clock):
    local = hlc_now(clock, None, "tablet-a")
    remote_ahead = "1792328999000-0003-tablet-b"
    merged = hlc_receive(local, remote_ahead, clock)
    assert merged == "1792328999000-0004-tablet-a"
    assert merged > local and parse_hlc(merged) > parse_hlc(remote_ahead)

    same_ms = hlc_receive("1792328999000-0007-tablet-a", "1792328999000-0002-tablet-b", clock)
    assert same_ms == "1792328999000-0008-tablet-a"

    clock.advance(1_000_000)
    assert hlc_receive(merged, remote_ahead, clock) == format_hlc(clock(), 0, "tablet-a")

    fresh = hlc_receive(None, remote_ahead, clock.__class__(0), device="phone-1")
    assert fresh == "1792328999000-0004-phone-1"
    with pytest.raises(ValueError):
        hlc_receive(None, remote_ahead, clock)


def test_send_receive_preserves_causality(clock):
    """A message from a device whose clock is far ahead still orders before every reply."""
    a_clock, b_clock = clock.__class__(1792328400000), clock.__class__(1792328000000)  # b is 400 s behind
    a = hlc_now(a_clock, None, "tablet-a")
    b = hlc_receive(None, a, b_clock, device="tablet-b")
    b2 = hlc_now(b_clock, b)
    assert a < b < b2
    assert compare_hlc(a, b) == -1 and compare_hlc(b2, b) == 1 and compare_hlc(a, a) == 0


def test_lexicographic_order_is_causal_order():
    values = ["1792328410000-000a-tablet-a", "1792328410000-0009-tablet-b", "1792328409999-ffff-tablet-a",
              "1792328410001-0000-hq"]
    assert sorted(values) == sorted(values, key=parse_hlc)
