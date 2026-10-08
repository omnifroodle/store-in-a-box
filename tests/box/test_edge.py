"""The Edge Server poll against a mocked Edge Server REST API (shapes from the Edge Server 1.1 API reference)."""

from __future__ import annotations

import asyncio

import httpx

from siab_box.edge import EdgeMonitor, file_credentials, replication_state

ROOT = {"couchdb": "Welcome", "vendor": {"name": "Couchbase Edge Server", "version": "1.1.0 (42; )"},
        "version": "CouchbaseEdgeServer/1.1.0 (42; ) CouchbaseLiteCore/3.3.0"}


def _task(status, error=None, target="ws://127.0.0.1:8790/store"):
    task = {"task_id": 1, "age_secs": 9, "type": "replication", "source": "retail", "target": target,
            "updated_on": 1760796000, "status": status}
    if error:
        task["error"] = {"error": error, "x-litecore-domain": 5, "x-litecore-code": 2}
    return task


def _monitor(clock, handler, creds=("siab-agent", "pw")):
    client = httpx.AsyncClient(base_url="http://edge.test", transport=httpx.MockTransport(handler))
    return EdgeMonitor(client, lambda: creds, clock, 8790, "app.example.test")


def _serve(tasks, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/":
            return httpx.Response(200, json=ROOT)
        if request.url.path == "/_replicate":
            return httpx.Response(200, json=tasks)
        return httpx.Response(404)

    return handler


def test_idle_replication_and_version(clock):
    seen = []
    monitor = _monitor(clock, _serve([_task("Idle")], seen))
    asyncio.run(monitor.poll_once())
    assert monitor.up and monitor.version == "1.1.0"
    assert monitor.replication_block() == {"state": "idle", "last_error": None, "checked_at": "2026-10-18T14:00:00Z"}
    assert seen[0].headers["authorization"].startswith("Basic ")


def test_states_after_a_cut(clock):
    for status, expected in (("Offline", "offline"), ("Connecting", "offline"), ("Stopped", "error"),
                             ("Busy", "busy"), ("Mystery", "unknown")):
        monitor = _monitor(clock, _serve([_task(status, error="connection refused")]))
        asyncio.run(monitor.poll_once())
        assert monitor.state == expected, status
        assert monitor.last_error == (None if expected == "busy" else "connection refused")


def test_picks_the_app_services_task_and_reports_its_absence(clock):
    other = _task("Busy", target="wss://elsewhere.example.test/db")
    monitor = _monitor(clock, _serve([other, _task("Idle")]))
    asyncio.run(monitor.poll_once())
    assert monitor.state == "idle"
    monitor = _monitor(clock, _serve([other]))
    asyncio.run(monitor.poll_once())
    assert monitor.state == "error" and "no replication" in monitor.last_error


def test_edge_server_down_is_unknown(clock):
    def handler(request):
        raise httpx.ConnectError("refused")

    monitor = _monitor(clock, handler)
    asyncio.run(monitor.poll_once())
    assert not monitor.up and monitor.state == "unknown" and "not reachable" in monitor.last_error


def test_refused_agent_user(clock):
    monitor = _monitor(clock, lambda request: httpx.Response(401))
    asyncio.run(monitor.poll_once())
    assert monitor.up and monitor.state == "unknown" and "render-config" in monitor.last_error


def test_poll_runs_on_virtual_time(clock):
    async def main():
        calls = []
        monitor = _monitor(clock, _serve([_task("Idle")], calls))
        task = asyncio.ensure_future(monitor.run())
        await clock.advance(0)
        await clock.advance(2)
        await clock.advance(2)
        task.cancel()
        assert len(calls) == 6  # three polls, two requests each
        assert monitor.checked_at == clock.now()

    asyncio.run(main())


def test_credentials_file(tmp_path):
    path = tmp_path / "agent.json"
    load = file_credentials(path)
    assert load() is None
    path.write_text('{"user": "siab-agent", "password": "pw"}')
    assert load() == ("siab-agent", "pw")


def test_replication_state_with_string_error():
    assert replication_state({"status": "Offline", "error": "gone"}) == ("offline", "gone")
