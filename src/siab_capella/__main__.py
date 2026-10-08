"""siab-capella: provision, seed and configure the Capella tier (docs/capella-setup.md).

Every subcommand prints its plan first. Nothing writes without --yes (`app-services verify` and `seed --diff` never
write). With --dry-run and no credentials in the environment, the plan is made offline: every step shows as `ensure`.
Exit codes: 0 done (or planned), 1 refused or failed, 2 manual steps left to do in the Capella UI.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

import httpx

from . import app_services, provision, seed
from .config import API_VARS, SDK_VARS, SEED_DIR, SYNC_DIR, Config
from .gateway import CapellaGateway
from .plan import Step, print_plan, run_plan

APP_VARS = API_VARS + ("CAPELLA_APP_SERVICE_ID",)
NEEDS = {
    "provision": SDK_VARS + API_VARS,
    "seed": SDK_VARS,
    "reset-trip": SDK_VARS,
    "apply": APP_VARS,
    "verify": ("APP_SERVICES_PUBLIC_URL",),
}


class Offline(Exception):  # noqa: N818
    pass


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    common.add_argument("--yes", action="store_true", help="apply the plan")
    common.add_argument("-v", "--verbose", action="store_true", help="also list the steps already in place")
    p = argparse.ArgumentParser(prog="siab-capella", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("provision", parents=[common], help="bucket, scopes, collections, indexes")
    s = sub.add_parser("seed", parents=[common], help="products, inventory and trips from the contract fixtures")
    s.add_argument("--trip", help="seed only this trip (default: SIAB_TRIP, else every trip in the fixtures)")
    s.add_argument("--diff", action="store_true", help="print live-versus-fixture differences; write nothing")
    a = sub.add_parser("app-services", help="the App Endpoint, sync functions and app users")
    asub = a.add_subparsers(dest="action", required=True)
    asub.add_parser("apply", parents=[common], help="create or update the endpoint from sync/app-endpoint.json")
    asub.add_parser("verify", parents=[common], help="connect as the box user and check its channels")
    r = sub.add_parser("reset-trip", parents=[common], help="delete a trip's allocations, transactions, exceptions")
    r.add_argument("--trip", required=True)
    return p


def main(argv: Sequence[str] | None = None, *, gateway: CapellaGateway | None = None, config: Config | None = None,
         out: TextIO | None = None) -> int:
    args = parser().parse_args(argv)
    config = config or Config.load()
    out = out or sys.stdout
    task = args.action if args.command == "app-services" else args.command

    def connect() -> CapellaGateway | None:
        if gateway is not None:
            return gateway
        missing = config.missing(NEEDS[task])
        if missing and args.dry_run:
            print(f"offline plan ({', '.join(missing)} not set): every step shows as ensure", file=out)
            return None
        if missing:
            raise Offline(f"{', '.join(missing)} not set (in .env or the environment); --dry-run plans offline")
        from .live import LiveCapella

        return LiveCapella(config)

    try:
        return _run(args, task, config, connect, out)
    except Offline as e:
        print(f"siab-capella {task}: {e}", file=out)
        return 1
    except ValueError as e:
        print(f"siab-capella {task}: {e}", file=out)
        return 1
    except Exception as e:  # a live-service failure: name it without a traceback (which could carry a URL)
        from .live import CapellaApiError

        if not isinstance(e, CapellaApiError | httpx.HTTPError):
            raise
        print(f"siab-capella {task}: {type(e).__name__}: {e}", file=out)
        return 1


def _run(args: argparse.Namespace, task: str, config: Config, connect, out: TextIO) -> int:
    if task == "provision":
        return _execute("provision", provision.plan_provision(connect()), args, out)

    if task == "seed":
        docs = seed.load_seed(SEED_DIR, args.trip or config.get("SIAB_TRIP") or None)
        if args.diff:
            gw = connect()
            if gw is None:
                raise Offline("--diff reads the live documents and needs the cluster")
            return _diff(seed.plan_seed(gw, docs), out)
        return _execute("seed", seed.plan_seed(connect(), docs), args, out)

    if task == "reset-trip":
        if not (args.yes or args.dry_run):
            print(f"reset-trip deletes every allocation, transaction and exception of {args.trip}: refusing "
                  "without --yes (--dry-run lists them)", file=out)
            return 1
        return _execute(f"reset-trip {args.trip}", seed.plan_reset_trip(connect(), args.trip), args, out)

    spec = app_services.load_endpoint(SYNC_DIR)
    problems = app_services.check_env(spec, config)
    for p in problems:
        print(f"problem: {p}", file=out)
    if problems:
        return 1
    if task == "apply":
        return _execute(f"app-services apply ({spec['name']})", app_services.plan_app_services(connect(), spec, config),
                        args, out)
    if args.dry_run:  # verify only reads, but a dry run opens no session at all
        box = app_services.box_user(spec)
        print(f"would connect to app endpoint {spec['name']} as {config.get(box['user_env'], box['name'])} and expect "
              f"{', '.join(box['channels'])} on {', '.join(spec['functions'])}", file=out)
        return 0
    return app_services.verify(connect(), spec, config, out)


def _execute(title: str, steps: list[Step], args: argparse.Namespace, out: TextIO) -> int:
    changes = print_plan(title, steps, out, verbose=args.verbose)
    refused = [s for s in steps if s.action == "refuse"]
    if args.dry_run or not args.yes:
        print("dry run: nothing written" if args.dry_run else "nothing written: re-run with --yes to apply", file=out)
        return 0
    if refused:
        print(f"refusing to apply: {len(refused)} step(s) cannot run (see above)", file=out)
        return 1
    if changes == 0:
        print("nothing to do", file=out)
        return 0
    manual = run_plan(steps, out)
    if manual:
        print("\nManual steps (the Management API does not cover these; then re-run):", file=out)
        for i, m in enumerate(manual, 1):
            print(f"{i}. {m}", file=out)
        return 2
    return 0


def _diff(steps: list[Step], out: TextIO) -> int:
    differing = [s for s in steps if s.change]
    for s in differing:
        print(f"{s.what}: {'missing from the cluster' if s.action == 'create' else 'differs'}", file=out)
        for d in s.detail:
            print(f"  {d}", file=out)
    print(f"{len(differing)} differences", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
