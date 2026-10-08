"""Fill box/edge-server/config.json.tmpl from the environment, and write Edge Server's users file beside it.

Edge Server 1.1 reads users from a separate JSON file of bcrypt hashes (`users` in the config). Besides the three
devices, the file holds the agent's own user (role `replicate`, needed to read `/_replicate`), whose random password
is written to `agent.json` for the agent. All three files are written mode 0600: the config holds BOX_APP_PASSWORD.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from .settings import DEFAULTS, DEVICES, REPO_ROOT, SettingsError, Target, edge_tls

TEMPLATE = REPO_ROOT / "box" / "edge-server" / "config.json.tmpl"
AGENT_USER = "siab-agent"
REQUIRED = ("APP_SERVICES_PUBLIC_URL", "BOX_APP_USER", "BOX_APP_PASSWORD", "SIAB_TRIP", "SIAB_REGION",
            *DEVICES.values())
PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")

Hasher = Callable[[str, str], str]


class RenderError(ValueError):
    pass


def htpasswd_hash(user: str, password: str) -> str:
    """bcrypt via `htpasswd` (pre-installed on macOS; apache2-utils on Linux), password on stdin, never in argv."""
    exe = shutil.which("htpasswd")
    if not exe:
        raise RenderError("htpasswd not found (macOS ships it; on Linux install apache2-utils)")
    done = subprocess.run([exe, "-niB", "-C", "10", user], input=password + "\n", capture_output=True, text=True,
                          check=False)
    line = done.stdout.strip()
    if done.returncode != 0 or ":" not in line:
        raise RenderError(f"htpasswd failed for {user}")
    return line.split(":", 1)[1]


def values(env: Mapping[str, str], edge_dir: Path) -> dict[str, str]:
    missing = [name for name in REQUIRED if not env.get(name)]
    if missing:
        raise RenderError("missing environment variables: " + ", ".join(missing))
    out = {**DEFAULTS, **{k: v for k, v in env.items() if v}}
    try:
        out["SIAB_ENDPOINT_PATH"] = Target.parse(env["APP_SERVICES_PUBLIC_URL"]).path
        edge_tls(env)
    except SettingsError as exc:
        raise RenderError(str(exc)) from exc
    out["SIAB_EDGE_DIR"] = str(edge_dir.resolve())
    return out


def render(template: str, env: Mapping[str, str], edge_dir: Path) -> dict:
    """The Edge Server config as a dict; refuses if any variable the template or the users file needs is missing."""
    filled = values(env, edge_dir)
    missing = sorted({name for name in PLACEHOLDER.findall(template) if name not in filled})
    if missing:
        raise RenderError("missing environment variables: " + ", ".join(missing))
    # every placeholder sits inside a JSON string, so each value goes in JSON-escaped
    text = PLACEHOLDER.sub(lambda m: json.dumps(filled[m.group(1)])[1:-1], template)
    config = json.loads(text)
    if edge_tls(env):
        config["https"] = {"tls_cert_path": filled["SIAB_EDGE_DIR"] + "/cert.pem",
                           "tls_key_path": filled["SIAB_EDGE_DIR"] + "/key.pem"}
    return config


def users(env: Mapping[str, str], agent_password: str, hasher: Hasher) -> dict:
    out = {device: {"password": hasher(device, env[name])} for device, name in DEVICES.items()}
    out[AGENT_USER] = {"password": hasher(AGENT_USER, agent_password), "roles": ["replicate"]}
    return out


def _write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.chmod(path, 0o600)


def write(out: Path, env: Mapping[str, str], hasher: Hasher | None = None,
          template_path: Path = TEMPLATE) -> list[Path]:
    """Write the config to `out` and users.json and agent.json beside it; returns the paths written."""
    hasher = hasher or htpasswd_hash
    edge_dir = out.parent
    config = render(template_path.read_text(encoding="utf-8"), env, edge_dir)
    agent_password = secrets.token_urlsafe(24)
    user_file = users(env, agent_password, hasher)  # hash everything before writing anything
    paths = [out, edge_dir / "users.json", edge_dir / "agent.json"]
    _write_private(paths[0], config)
    _write_private(paths[1], user_file)
    _write_private(paths[2], {"user": AGENT_USER, "password": agent_password})
    return paths
