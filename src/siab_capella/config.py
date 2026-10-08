"""The `.env` variables (docs/workstreams/WS2-capella-sync.md, "Interfaces"; the names are the contract) and where
the CLI finds the fixtures and the sync functions."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "contracts" / "fixtures" / "seed"
SYNC_DIR = ROOT / "sync"

ENV_VARS = (
    "CAPELLA_CONN_STRING",
    "CAPELLA_DB_USERNAME",
    "CAPELLA_DB_PASSWORD",
    "CAPELLA_API_KEY",
    "CAPELLA_API_BASE",
    "CAPELLA_ORG_ID",
    "CAPELLA_PROJECT_ID",
    "CAPELLA_CLUSTER_ID",
    "CAPELLA_APP_SERVICE_ID",
    "APP_SERVICES_PUBLIC_URL",
    "APP_SERVICES_ADMIN_URL",
    "SIAB_TRIP",
    "SIAB_REGION",
    "BOX_APP_USER",
    "BOX_APP_PASSWORD",
    "HQ_APP_USER",
    "HQ_APP_PASSWORD",
)

# What the SDK needs (documents, queries, indexes) and what the Management API needs (bucket, scopes, collections,
# App Services). A dry run without them plans offline.
SDK_VARS = ("CAPELLA_CONN_STRING", "CAPELLA_DB_USERNAME", "CAPELLA_DB_PASSWORD")
API_VARS = ("CAPELLA_API_KEY", "CAPELLA_API_BASE", "CAPELLA_ORG_ID", "CAPELLA_PROJECT_ID", "CAPELLA_CLUSTER_ID")


def read_dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments skipped; one layer of matching quotes stripped."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


@dataclass(frozen=True)
class Config:
    env: Mapping[str, str]

    @classmethod
    def load(cls, env: Mapping[str, str] | None = None, dotenv: Path | None = None) -> Config:
        """The process environment over `.env` (in the working directory), unless `env` is given."""
        if env is not None:
            return cls(dict(env))
        merged = read_dotenv(dotenv or Path.cwd() / ".env")
        merged.update({k: v for k, v in os.environ.items() if k in ENV_VARS})
        return cls(merged)

    def get(self, name: str, default: str = "") -> str:
        return self.env.get(name, "") or default

    def missing(self, names: tuple[str, ...]) -> list[str]:
        return [n for n in names if not self.get(n)]

    @property
    def online(self) -> bool:
        return not self.missing(SDK_VARS + API_VARS)
