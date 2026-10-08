"""Environment names the box reads, their defaults, and the devices it pairs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

# The devices paired to box-07 and the variable holding each one's Edge Server password
# (contracts/fixtures/seed/custodians.json: kind "device", edge_user).
DEVICES: dict[str, str] = {
    "tablet-a": "EDGE_TABLET_A_PASSWORD",
    "tablet-b": "EDGE_TABLET_B_PASSWORD",
    "phone-1": "EDGE_PHONE_1_PASSWORD",
}

DEFAULTS: dict[str, str] = {
    "EDGE_PORT": "59840",
    "EDGE_TLS": "off",
    "SIAB_BOX_PORT": "8787",
    "SIAB_PROXY_PORT": "8790",
    "SIAB_BOX_ID": "box-07",
}

# What the agent cannot run without (render-config needs BOX_APP_USER, BOX_APP_PASSWORD and SIAB_REGION too).
AGENT_REQUIRED = ("APP_SERVICES_PUBLIC_URL", "SIAB_TRIP", *DEVICES.values())

REPO_ROOT = Path(__file__).resolve().parents[2]
EDGE_DIR = REPO_ROOT / "box" / ".edge-server"


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    """The App Services endpoint the proxy relays to, split from APP_SERVICES_PUBLIC_URL."""

    host: str
    port: int
    tls: bool
    path: str

    @property
    def authority(self) -> str:
        default = 443 if self.tls else 80
        return self.host if self.port == default else f"{self.host}:{self.port}"

    @classmethod
    def parse(cls, url: str) -> Target:
        parts = urlsplit(url)
        if parts.scheme not in ("ws", "wss") or not parts.hostname:
            raise SettingsError("APP_SERVICES_PUBLIC_URL must be a ws:// or wss:// URL with a host")
        tls = parts.scheme == "wss"
        path = parts.path.rstrip("/")
        if not path:
            raise SettingsError("APP_SERVICES_PUBLIC_URL must name the App Endpoint in its path")
        return cls(parts.hostname, parts.port or (443 if tls else 80), tls, path)


def _port(env: Mapping[str, str], name: str) -> int:
    value = env.get(name) or DEFAULTS[name]
    if not value.isdigit() or not 0 < int(value) < 65536:
        raise SettingsError(f"{name} must be a port number, not {value!r}")
    return int(value)


def edge_tls(env: Mapping[str, str]) -> bool:
    value = (env.get("EDGE_TLS") or DEFAULTS["EDGE_TLS"]).lower()
    if value not in ("on", "off"):
        raise SettingsError(f"EDGE_TLS must be on or off, not {value!r}")
    return value == "on"


@dataclass(frozen=True)
class Settings:
    box_id: str
    trip: str
    target: Target
    edge_port: int
    edge_tls: bool
    box_port: int
    proxy_port: int
    device_passwords: dict[str, str]
    edge_dir: Path = EDGE_DIR

    @classmethod
    def from_env(cls, env: Mapping[str, str], edge_dir: Path = EDGE_DIR) -> Settings:
        missing = [name for name in AGENT_REQUIRED if not env.get(name)]
        if missing:
            raise SettingsError("missing environment variables: " + ", ".join(missing))
        return cls(
            box_id=env.get("SIAB_BOX_ID") or DEFAULTS["SIAB_BOX_ID"],
            trip=env["SIAB_TRIP"],
            target=Target.parse(env["APP_SERVICES_PUBLIC_URL"]),
            edge_port=_port(env, "EDGE_PORT"),
            edge_tls=edge_tls(env),
            box_port=_port(env, "SIAB_BOX_PORT"),
            proxy_port=_port(env, "SIAB_PROXY_PORT"),
            device_passwords={device: env[name] for device, name in DEVICES.items()},
            edge_dir=edge_dir,
        )

    @property
    def cert_path(self) -> Path:
        return self.edge_dir / "cert.pem"

    @property
    def agent_credentials_path(self) -> Path:
        return self.edge_dir / "agent.json"
