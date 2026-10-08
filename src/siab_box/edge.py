"""Edge Server as the agent sees it: up or not, its version, and the state of the replication to App Services.

Reads `GET /` (vendor version) and `GET /_replicate` (one item per replication task, `status` is the replicator's
activity level, e.g. "Idle", "Busy", "Offline") with the agent's own Edge Server user, whose credentials
render-config writes to `box/.edge-server/agent.json`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx

from .clock import Clock, iso

POLL_INTERVAL = 2.0

# Couchbase Lite replicator activity levels as Edge Server reports them, lower-cased, to the status API's states.
STATES = {
    "idle": "idle",
    "busy": "busy",
    "offline": "offline",
    "connecting": "offline",
    "stopped": "error",
    "stopping": "error",
}

Credentials = Callable[[], tuple[str, str] | None]


def file_credentials(path: Path) -> Credentials:
    """Read on every poll, so a re-render while the agent runs is picked up."""

    def load() -> tuple[str, str] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data["user"], data["password"]
        except (OSError, ValueError, KeyError):
            return None

    return load


def short_version(vendor_version: str) -> str:
    """'1.1.0 (37; )' -> '1.1.0'."""
    return vendor_version.split(" ", 1)[0]


def pick_replication(tasks: list[dict], proxy_port: int, target_host: str) -> dict | None:
    """The task replicating to App Services: through the proxy, or straight to the App Services host."""
    marks = (f"127.0.0.1:{proxy_port}", f"localhost:{proxy_port}", target_host)
    for task in tasks:
        if task.get("type", "replication") != "replication":
            continue
        ends = f"{task.get('source', '')} {task.get('target', '')}"
        if any(mark in ends for mark in marks):
            return task
    return None


def replication_state(task: dict | None) -> tuple[str, str | None]:
    if task is None:
        return "error", "no replication to App Services is running"
    state = STATES.get(str(task.get("status", "")).lower(), "unknown")
    error = task.get("error")
    message = (error.get("error") or json.dumps(error)) if isinstance(error, dict) else error
    if state in ("idle", "busy"):
        message = None
    return state, message


class EdgeMonitor:
    def __init__(self, client: httpx.AsyncClient, credentials: Credentials, clock: Clock, proxy_port: int,
                 target_host: str, interval: float = POLL_INTERVAL):
        self.client = client
        self.credentials = credentials
        self.clock = clock
        self.proxy_port = proxy_port
        self.target_host = target_host
        self.interval = interval
        self.up = False
        self.version: str | None = None
        self.state = "unknown"
        self.last_error: str | None = None
        self.checked_at = clock.now()

    async def poll_once(self) -> None:
        creds = self.credentials()
        auth = httpx.BasicAuth(*creds) if creds else None
        try:
            root = await self.client.get("/", auth=auth)
            if root.status_code == 401:
                self.up, self.state = True, "unknown"
                self.last_error = "the agent's Edge Server user was refused; re-run render-config and restart"
                return
            root.raise_for_status()
            self.up = True
            self.version = short_version(root.json().get("vendor", {}).get("version", "")) or None
            tasks = await self.client.get("/_replicate", auth=auth)
            tasks.raise_for_status()
            body = tasks.json()
            self.state, self.last_error = replication_state(
                pick_replication(body if isinstance(body, list) else [], self.proxy_port, self.target_host))
        except httpx.TransportError as exc:
            self.up, self.state = False, "unknown"
            self.last_error = f"Edge Server not reachable: {exc.__class__.__name__}"
        except (httpx.HTTPStatusError, ValueError) as exc:
            self.state = "unknown"
            self.last_error = f"unexpected answer from Edge Server: {exc}"
        finally:
            self.checked_at = self.clock.now()

    async def run(self) -> None:
        while True:
            await self.poll_once()
            await self.clock.sleep(self.interval)

    def replication_block(self) -> dict:
        return {"state": self.state, "last_error": self.last_error, "checked_at": iso(self.checked_at)}
