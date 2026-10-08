"""`app-services apply|verify`: the App Endpoint `store` over scope `store`, one sync function per linked collection,
and the app users, all from sync/app-endpoint.json. Each user's channels apply to every linked collection."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, TextIO

from .config import Config
from .gateway import CapellaGateway, Channels, ManualStepRequired
from .plan import Step

NEVER_LINKED = ("inventory",)  # store-only: on-hand never reaches a venue


def load_endpoint(sync_dir: Path) -> dict[str, Any]:
    """app-endpoint.json, with `functions` (collection -> source) read from the files it names."""
    spec = json.loads((sync_dir / "app-endpoint.json").read_text(encoding="utf-8"))
    spec["functions"] = {c: (sync_dir / p).read_text(encoding="utf-8") for c, p in spec["collections"].items()}
    linked = sorted(set(spec["functions"]) & set(NEVER_LINKED))
    if linked:
        raise ValueError(f"app-endpoint.json links {', '.join(linked)}, which must never reach a venue")
    return spec


def grants(spec: dict[str, Any], user: dict[str, Any]) -> Channels:
    return {c: sorted(user["channels"]) for c in spec["functions"]}


def box_user(spec: dict[str, Any]) -> dict[str, Any]:
    return next(u for u in spec["users"] if u["user_env"] == "BOX_APP_USER")


def _normalise(channels: Channels, collections: list[str]) -> Channels:
    return {c: sorted(set(channels.get(c, [])) - {"!"}) for c in collections}  # "!" is the public channel


def _paste(run: Callable[[], object], spec: dict[str, Any], collections: list[str]) -> Callable[[], None]:
    """Run a step; if it needs the Capella UI, add the function bodies to paste to its manual steps."""

    def wrapped() -> None:
        try:
            run()
        except ManualStepRequired as e:
            for c in collections:
                e.steps.append(f"Paste as the access control function of {spec['name']} > {spec['scope']}.{c} "
                               f"(sync/{spec['collections'][c]}):\n{spec['functions'][c].rstrip()}")
            raise

    return wrapped


def _manual(steps: list[str]) -> Callable[[], None]:
    def run() -> None:
        raise ManualStepRequired(steps)

    return run


def plan_app_services(gw: CapellaGateway | None, spec: dict[str, Any], config: Config) -> list[Step]:
    name, bucket, scope, functions = spec["name"], spec["bucket"], spec["scope"], spec["functions"]
    colls = list(functions)
    steps: list[Step] = []
    if gw is None:
        steps.append(Step("ensure", f"app endpoint {name} over {bucket}.{scope}"))
        steps += [Step("ensure", f"sync function {name} > {scope}.{c}") for c in colls]
        steps += [Step("ensure", f"user {u['name']} on {name}") for u in spec["users"]]
        return steps

    live = gw.app_services_get_endpoint(name)
    if live is None:
        what = f"app endpoint {name} over {bucket}.{scope} linking {', '.join(colls)}"
        run = _paste(lambda: gw.app_services_create_endpoint(name, bucket, scope, functions), spec, colls)
        steps.append(Step("create", what, run))
    elif (live.bucket, live.scope) != (bucket, scope):
        what = f"app endpoint {name} is over {live.bucket}.{live.scope}, not {bucket}.{scope}"
        steps.append(Step("manual", what, _manual([f"Delete or rename app endpoint {name} in the Capella UI, then "
                                                   "re-run app-services apply."])))
    else:
        for c, src in functions.items():
            what = f"sync function {name} > {scope}.{c}"
            if c not in live.functions:
                run = _paste(lambda c=c, s=src: gw.app_services_link_collection(name, scope, c, s), spec, [c])
                steps.append(Step("create", f"link {scope}.{c} to {name}; {what}", run))
            elif live.functions[c].strip() != src.strip():
                run = _paste(lambda c=c, s=src: gw.app_services_set_sync_function(name, scope, c, s), spec, [c])
                steps.append(Step("update", what, run))
            else:
                steps.append(Step("unchanged", what))
        for c in sorted(set(live.functions) - set(functions)):
            steps.append(Step("manual", f"{scope}.{c} is linked to {name} but not in app-endpoint.json",
                              _manual([f"Unlink {scope}.{c} from app endpoint {name} in the Capella UI."])))

    live_users = gw.app_services_get_users(name) if live is not None else {}
    for u in spec["users"]:
        want = grants(spec, u)
        password = config.get(u["password_env"]) or None
        what = f"user {u['name']} on {name}: {', '.join(u['channels'])} on {len(colls)} collection(s)"
        if u["name"] not in live_users:
            if password is None:
                steps.append(Step("refuse", what, detail=[f"{u['password_env']} is not set"]))
            else:
                steps.append(Step("create", what, partial(gw.app_services_put_user, name, scope, u["name"], want,
                                                          password)))
        elif _normalise(live_users[u["name"]], colls) != want:  # an update keeps the user's password
            steps.append(Step("update", what, partial(gw.app_services_put_user, name, scope, u["name"], want, None)))
        else:
            steps.append(Step("unchanged", what))
    return steps


def check_env(spec: dict[str, Any], config: Config) -> list[str]:
    """Problems between .env and app-endpoint.json: a renamed user, or a default trip or region the box cannot see."""
    out: list[str] = []
    for u in spec["users"]:
        env_name = config.get(u["user_env"])
        if env_name and env_name != u["name"]:
            out.append(f"{u['user_env']}={env_name} but app-endpoint.json names the user {u['name']}")
    box = box_user(spec)
    for var, prefix in (("SIAB_TRIP", "trip:"), ("SIAB_REGION", "catalog:")):
        value = config.get(var)
        if value and prefix + value not in box["channels"]:
            out.append(f"{var}={value} but {box['name']} is not granted {prefix}{value}")
    return out


def verify(gw: CapellaGateway, spec: dict[str, Any], config: Config, out: TextIO) -> int:
    """Connect as the box user and compare its channels per linked collection with app-endpoint.json."""
    box = box_user(spec)
    user = config.get(box["user_env"], box["name"])
    password = config.get(box["password_env"])
    if not password:
        print(f"{box['password_env']} is not set", file=out)
        return 1
    try:
        got = gw.app_services_session(user, password, spec["scope"], list(spec["functions"]))
    except Exception as e:  # noqa: BLE001 (any refusal or transport error is a failed verify; say which)
        print(f"session as {user} on {spec['name']} failed: {type(e).__name__}: {e}", file=out)
        return 1
    want = grants(spec, box)
    got_n = _normalise(got, sorted(set(got) | set(want)))
    print(f"session as {user} on {spec['name']}: ok", file=out)
    bad = 0
    for c in sorted(set(got_n) | set(want)):
        if c not in want:
            print(f"  {c}: not expected to be linked, granted {got_n[c]}", file=out)
            bad += 1
        elif got_n.get(c) != want[c]:
            print(f"  {c}: granted {got_n.get(c, [])}, expected {want[c]}", file=out)
            bad += 1
        else:
            print(f"  {c}: {', '.join(want[c])}", file=out)
    print("channels as expected" if bad == 0 else f"{bad} collection(s) differ", file=out)
    return 0 if bad == 0 else 1
