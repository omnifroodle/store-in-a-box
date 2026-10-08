"""siab-hq: the HQ screen and the Capella-side reconciler (``ports/hq.md``).

    python -m siab_hq serve [--trip ID] [--port N]
    python -m siab_hq reconcile --once [--trip ID] [--dry-run]

Capella credentials come from ``.env`` (``CAPELLA_CONN_STRING``, ``CAPELLA_DB_USERNAME``, ``CAPELLA_DB_PASSWORD``).
``SIAB_HQ_FAKE=<ledger fixture name or path>`` runs against WS2's ``FakeCapella`` loaded from that fixture instead.
Exit codes: 0 done, 1 refused or failed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TextIO

from siab_capella.config import SDK_VARS, Config, read_dotenv
from siab_capella.gateway import CapellaGateway

from . import queries
from .reconcile import Hq
from .server import App, serve

DEFAULT_PORT = 8788
DEFAULT_INTERVAL_S = 3.0


class Refused(Exception):  # noqa: N818
    pass


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="siab-hq", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="the HQ screen and API, with the reconciler running")
    s.add_argument("--trip", help="the trip (default: SIAB_TRIP)")
    s.add_argument("--port", type=int, help=f"the port on 127.0.0.1 (default: SIAB_HQ_PORT, else {DEFAULT_PORT})")
    r = sub.add_parser("reconcile", help="write HQ's exceptions for the trip")
    r.add_argument("--trip", help="the trip (default: SIAB_TRIP)")
    r.add_argument("--once", action="store_true", help="run once and exit (else every SIAB_RECONCILE_INTERVAL_S)")
    r.add_argument("--dry-run", action="store_true", help="print the exception ids it would write; write nothing")
    return p


def settings(env: Mapping[str, str] | None) -> dict[str, str]:
    """The process environment over ``.env`` (in the working directory), unless ``env`` is given."""
    if env is not None:
        return dict(env)
    return {**read_dotenv(Path.cwd() / ".env"), **os.environ}


def connect(env: Mapping[str, str]) -> tuple[CapellaGateway, str | None]:
    """The gateway, and the trip of the fake's fixture when ``SIAB_HQ_FAKE`` selects the fake."""
    if env.get("SIAB_HQ_FAKE"):
        gw, fixture = queries.fake_gateway(env["SIAB_HQ_FAKE"])
        return gw, fixture["trip"]
    config = Config.load(env=dict(env))
    if missing := config.missing(SDK_VARS):
        raise Refused(f"{', '.join(missing)} not set (in .env or the environment); SIAB_HQ_FAKE selects the fake")
    from siab_capella.live import LiveCapella

    return LiveCapella(config), None


def wall_clock() -> int:
    return time.time_ns() // 1_000_000


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None,
         gateway: CapellaGateway | None = None, clock: Callable[[], int] = wall_clock,
         out: TextIO | None = None) -> int:
    args = parser().parse_args(argv)
    env = settings(env)
    out = out or sys.stdout
    try:
        gw, fixture_trip = (gateway, None) if gateway is not None else connect(env)
        trip = args.trip or env.get("SIAB_TRIP") or fixture_trip
        if not trip:
            raise Refused("no trip: pass --trip or set SIAB_TRIP")
        hq = Hq(gw, trip, clock)
        interval = float(env.get("SIAB_RECONCILE_INTERVAL_S") or DEFAULT_INTERVAL_S)
        if args.command == "reconcile":
            planned = hq.run_once(dry_run=args.dry_run)
            verb = "would write" if args.dry_run else "wrote"
            for doc in planned:
                print(f"{verb} {doc['_id']}", file=out)
            if not planned:
                print(f"nothing to write for {trip}", file=out)
            if not args.once:
                asyncio.run(hq.run_every(interval))
            return 0
        port = args.port or int(env.get("SIAB_HQ_PORT") or DEFAULT_PORT)
        app = App(hq, box_status_url=env.get("SIAB_BOX_STATUS_URL", ""))
        asyncio.run(_serve(app, port, interval, out))
        return 0
    except (Refused, queries.TripNotFound) as e:
        print(f"siab-hq {args.command}: {e}", file=out)
        return 1
    except KeyboardInterrupt:
        return 0


async def _serve(app: App, port: int, interval: float, out: TextIO) -> None:
    try:
        await asyncio.to_thread(app.hq.run_once)  # once at startup
    except queries.TripNotFound:
        raise
    except Exception as e:  # noqa: BLE001 (the screen still comes up and says so in /api/reconcile/status)
        app.hq.status.last_error = f"{type(e).__name__}: {e}"
    server = await serve(app, port)
    print(f"siab-hq: http://127.0.0.1:{port}/ (trip {app.hq.trip}, reconcile every {interval:g} s)", file=out,
          flush=True)
    loop = asyncio.create_task(app.hq.run_every(interval))
    try:
        async with server:
            await server.serve_forever()
    finally:
        loop.cancel()


if __name__ == "__main__":
    sys.exit(main())
