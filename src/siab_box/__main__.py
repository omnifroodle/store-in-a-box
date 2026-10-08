"""python -m siab_box {agent|dev|render-config}"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from . import agent, render_config
from .settings import AGENT_REQUIRED, EDGE_DIR, Settings, SettingsError

# `dev` stands these in for whatever is unset, so the status page can be worked on without a full .env.
DEV_DEFAULTS = {
    "SIAB_TRIP": "trip-2026-10-18-riverfest",
    "APP_SERVICES_PUBLIC_URL": "wss://app-services.invalid:4984/store",
    "EDGE_TABLET_A_PASSWORD": "dev-only",
    "EDGE_TABLET_B_PASSWORD": "dev-only",
    "EDGE_PHONE_1_PASSWORD": "dev-only",
}


def _run_agent(env: dict[str, str], args: argparse.Namespace) -> int:
    try:
        settings = Settings.from_env(env)
    except SettingsError as exc:
        print(f"siab-box: {exc}", file=sys.stderr)
        return 2
    try:
        asyncio.run(agent.run(settings, host_ip=args.lan_ip, edge_url=getattr(args, "edge_url", None)))
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"siab-box: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="siab-box", description="The box agent beside Couchbase Edge Server.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_agent = sub.add_parser("agent", help="run the counting proxy and the status server")
    p_agent.add_argument("--lan-ip", help="address the tablets use to reach this box (default: detected)")
    p_dev = sub.add_parser("dev", help="agent only, against an Edge Server already running locally; "
                                       "fills unset variables with dev placeholders")
    p_dev.add_argument("--lan-ip")
    p_dev.add_argument("--edge-url", help="Edge Server base URL (default: from EDGE_PORT and EDGE_TLS)")
    p_render = sub.add_parser("render-config", help="fill box/edge-server/config.json.tmpl from the environment")
    p_render.add_argument("--out", type=Path, default=EDGE_DIR / "config.json",
                          help="config path; users.json and agent.json are written beside it")
    args = parser.parse_args(argv)
    env = dict(os.environ)

    if args.command == "render-config":
        try:
            for path in render_config.write(args.out, env):
                print(f"wrote {path}")
        except render_config.RenderError as exc:
            print(f"siab-box render-config: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "dev":
        filled = [name for name in AGENT_REQUIRED if not env.get(name)]
        for name in filled:
            env[name] = DEV_DEFAULTS[name]
        if filled:
            print("siab-box dev: placeholders for " + ", ".join(filled), file=sys.stderr)
    return _run_agent(env, args)


if __name__ == "__main__":
    raise SystemExit(main())
