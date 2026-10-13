"""The rehearsal scripts: reset refuses without --yes and writes nothing; stage_oversell talks to a stub HQ."""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESET = ROOT / "scripts" / "demo" / "reset_rehearsal.sh"
STAGE = ROOT / "scripts" / "demo" / "stage_oversell.sh"


def run(script, *args, env=None, cwd=None):
    full = {**os.environ, **(env or {})}
    return subprocess.run([str(script), *args], capture_output=True, text=True, env=full, cwd=cwd, timeout=30)


def test_reset_without_yes_exits_2_and_writes_nothing(tmp_path):
    # A fake `uv` and `curl` first on the PATH record any call; the refusal must make none.
    log = tmp_path / "calls.log"
    for tool in ("uv", "curl"):
        fake = tmp_path / tool
        fake.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\n')
        fake.chmod(0o755)
    env = {"PATH": f"{tmp_path}:{os.environ['PATH']}", "SIAB_TRIP": "trip-test"}
    for args in ((), ("--dry-run",), ("--yes", "extra")):
        r = run(RESET, *args, env=env, cwd=tmp_path)
        assert r.returncode == 2, r.stderr
        assert not log.exists()
    assert list(tmp_path.glob("*.json")) == []


def test_reset_with_yes_runs_the_three_steps_in_order(tmp_path):
    log = tmp_path / "calls.log"
    for tool in ("uv", "curl"):
        fake = tmp_path / tool
        fake.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\n')
        fake.chmod(0o755)
    env = {"PATH": f"{tmp_path}:{os.environ['PATH']}", "SIAB_TRIP": "trip-test", "SIAB_BOX_STATUS_URL": "http://box.invalid:1/"}
    r = run(RESET, "--yes", env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    calls = log.read_text().splitlines()
    assert calls == [
        "uv run python -m siab_capella reset-trip --trip trip-test --yes",
        "uv run python -m siab_capella seed --yes",
        "curl -fsS --max-time 5 -X POST http://box.invalid:1/bytes/reset",
    ]
    assert "Rebuild derived state" in r.stdout


def _fakes(tmp_path, reset_output=""):
    log = tmp_path / "calls.log"
    uv = tmp_path / "uv"
    uv.write_text(f'#!/bin/sh\necho "uv $*" >> "{log}"\ncase "$*" in *reset-trip*) echo "{reset_output}";; esac\n')
    uv.chmod(0o755)
    curl = tmp_path / "curl"
    curl.write_text(f'#!/bin/sh\necho "curl $*" >> "{log}"\n')
    curl.chmod(0o755)
    return log, {"PATH": f"{tmp_path}:{os.environ['PATH']}", "SIAB_TRIP": "", "SIAB_BOX_STATUS_URL": ""}


def test_reset_reads_dotenv_like_the_python_tools(tmp_path):
    # Not exported: the quotes and the `export ` prefix must not reach the command line.
    for line in ('SIAB_TRIP="trip-2026-10-18-riverfest"', "export SIAB_TRIP='trip-2026-10-18-riverfest'",
                 "  export SIAB_TRIP = trip-2026-10-18-riverfest  "):
        log, env = _fakes(tmp_path, "reset-trip x: 3 change(s)")
        env.pop("SIAB_TRIP")
        env.pop("SIAB_BOX_STATUS_URL")
        (tmp_path / ".env").write_text(f"# c\n{line}\nSIAB_BOX_STATUS_URL=\"http://box.invalid:1/\"\n")
        log.unlink(missing_ok=True)
        r = run(RESET, "--yes", env=env, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert log.read_text().splitlines() == [
            "uv run python -m siab_capella reset-trip --trip trip-2026-10-18-riverfest --yes",
            "uv run python -m siab_capella seed --yes",
            "curl -fsS --max-time 5 -X POST http://box.invalid:1/bytes/reset",
        ]


def test_reset_stops_when_reset_trip_finds_nothing(tmp_path):
    log, env = _fakes(tmp_path, "reset-trip x: 0 change(s), 3 already in place\nnothing to do")
    env["SIAB_TRIP"] = "trip-typo"
    r = run(RESET, "--yes", env=env, cwd=tmp_path)
    assert r.returncode == 1
    assert "found no documents" in r.stderr
    assert "Done in Capella" not in r.stdout
    assert log.read_text().splitlines() == ["uv run python -m siab_capella reset-trip --trip trip-typo --yes"]


class StubHq(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        StubHq.seen.append((self.path, json.loads(body)))
        unit = json.loads(body)["unit_id"]
        ok = unit in ("JKT-RAIN-M-BLU#001", "JKT-RAIN-M-BLU#003")
        payload = {"id": "txn::1792329100000-0000-hq"} if unit.endswith("#001") else {"ok": True}
        if not ok:
            payload = {"error": "not held by the box"}
        data = json.dumps(payload).encode()
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def with_stub(fn):
    server = HTTPServer(("127.0.0.1", 0), StubHq)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return fn(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


def test_stage_oversell_prints_the_transaction_and_the_dispute():
    StubHq.seen.clear()
    r = with_stub(lambda port: run(STAGE, "JKT-RAIN-M-BLU#001", env={"SIAB_HQ_PORT": str(port)}))
    assert r.returncode == 0, r.stderr
    assert StubHq.seen == [("/api/stage/hq-sale", {"unit_id": "JKT-RAIN-M-BLU#001"})]
    assert "txn::1792329100000-0000-hq" in r.stdout
    assert "oversell" in r.stdout and "JKT-RAIN-M-BLU#001|root" in r.stdout


def test_stage_oversell_survives_an_answer_without_an_id():
    # HQ answers 200 with no "id": the script must reach its fallback message, not die under `set -euo pipefail`.
    r = with_stub(lambda port: run(STAGE, "JKT-RAIN-M-BLU#003", env={"SIAB_HQ_PORT": str(port)}))
    assert r.returncode == 0, r.stderr
    assert "staged HQ sale: <no id in the answer>" in r.stdout
    assert "JKT-RAIN-M-BLU#003|root" in r.stdout


def test_stage_oversell_reports_a_refusal():
    r = with_stub(lambda port: run(STAGE, "JKT-RAIN-M-BLU#002", env={"SIAB_HQ_PORT": str(port)}))
    assert r.returncode == 1
    assert "HQ refused (400)" in r.stderr


def test_stage_oversell_rejects_a_malformed_unit():
    assert run(STAGE, "nope").returncode == 64
    assert run(STAGE).returncode == 64
