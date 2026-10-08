"""The uplink probe on virtual time: every 5 s, a connect that takes longer than 2 s means unreachable."""

from __future__ import annotations

import asyncio

from siab_box.uplink import Uplink, UplinkProbe


class FakeConnect:
    def __init__(self):
        self.mode = "ok"
        self.calls = 0

    async def __call__(self, host, port):
        self.calls += 1
        if self.mode == "refuse":
            raise ConnectionRefusedError
        if self.mode == "hang":
            await asyncio.Event().wait()


def test_uplink_flips_to_unreachable_after_timeout(clock):
    async def main():
        uplink = Uplink(clock, "app.example.test")
        connect = FakeConnect()
        task = asyncio.ensure_future(UplinkProbe(uplink, 4984, clock, connect).run())
        await clock.advance(0)
        assert uplink.reachable and connect.calls == 1
        up_since = uplink.since

        connect.mode = "hang"  # the WAN cable comes out: SYNs go nowhere
        await clock.advance(5)  # the next probe starts
        assert connect.calls == 2 and uplink.reachable
        await clock.advance(1.9)
        assert uplink.reachable  # not yet: the timeout is 2 s
        await clock.advance(0.1)
        assert not uplink.reachable and not uplink.cut
        assert uplink.since == clock.now() and uplink.since > up_since

        connect.mode = "ok"
        await clock.advance(5)
        assert uplink.reachable
        task.cancel()

    asyncio.run(main())


def test_refused_connection_is_unreachable_at_once(clock):
    async def main():
        uplink = Uplink(clock, "app.example.test")
        connect = FakeConnect()
        connect.mode = "refuse"
        probe = UplinkProbe(uplink, 4984, clock, connect)
        assert await probe.probe_once() is False
        assert clock.t == 0

    asyncio.run(main())


def test_probe_within_ten_seconds_of_the_cable(clock):
    """The blueprint's physical-cut promise: the page shows unreachable within 10 s of the cable coming out."""

    async def main():
        uplink = Uplink(clock, "app.example.test")
        connect = FakeConnect()
        task = asyncio.ensure_future(UplinkProbe(uplink, 4984, clock, connect).run())
        await clock.advance(0.5)  # worst case: the cable comes out just after a probe succeeded
        connect.mode = "hang"
        await clock.advance(4.5 + 2)  # next probe at 5 s, timeout 2 s later
        assert not uplink.reachable and clock.t <= 10
        task.cancel()

    asyncio.run(main())
