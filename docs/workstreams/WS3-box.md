# WS3: The box: Couchbase Edge Server config, box agent and byte counter

**Milestone:** M1  **Depends on:** contracts v0.1 (CC1, CC4); WS2 for the live tasks only  **Label:** `ws:3-box`  **Agent type:** ws-design
**Issue:** #14

The blueprint. The architect (`ws-architect`) writes it before any code is dispatched; the PR is judged against it.
Amended 2026-10-07 for D4 (#9): the supported Phase 0 box is a macOS laptop; the Raspberry Pi is best-effort.

## Scope

The venue hub. Couchbase Edge Server 1.1 on the **macOS laptop that is the Phase 0 box** (decision 002; Edge
Server 1.1 lists macOS 13+ on Intel and Apple silicon, and ships for macOS as a zip holding one binary that is run
with a JSON config path), configured with the `retail` database, scope `store` and the five venue collections,
local users for the tablets and the phone, and a continuous bidirectional replication to Capella App Services.
Beside it runs the **box agent**, a small Python process that (a) counts the bytes of the uplink replication so the
demo can show "a day in kilobytes", (b) serves a status page with the byte counter, uplink state, Edge Server state
and replication state, (c) renders the pairing QR each tablet scans to learn the box's address and its credentials,
and (d) is the box's **software uplink**: every byte Edge Server sends to App Services passes through the agent's
proxy, so "cut the uplink" is something the agent can do on any OS. Plus the install script, the foreground runner
and the `uplink.sh` helper.

**What the cable pull means on a laptop.** The laptop and the tablets share the travel router's LAN; the box's
uplink is the router's WAN. There is no cable on the laptop to pull, and turning the laptop's Wi-Fi off would cut
the tablets too. So there are two cuts, and Edge Server cannot tell them apart (a connection drops, a retry fails,
a resume from checkpoint when it is back): the **physical** one on stage is the router's WAN cable (D7 below), and
the **software** one for rehearsals and the one-laptop setup is `uplink.sh cut`, which makes the agent's proxy stop
relaying. The status page shows which it is.

**The Pi is optional.** The owner's Raspberry Pi runs Debian Trixie, which Edge Server 1.1 does not list for ARM64
(Ubuntu 22.04+ only). The Linux path survives only as a bounded branch of `install.sh` plus two systemd units, no
exit criterion runs on it, and whether Edge Server runs on Trixie arm64 at all is a verification item, not a task.

The box runs **no custody logic** in Phase 0: tablets compute their own ledger (WS4) and HQ computes the cloud's
(WS5). The box moves documents. That is the point of the box.

Left for later: the small model runtime and on-box agents (Phase 1), encryption key vending (Phase 1), throttling
to 2G and the checkpoint demo (showcase 9; `uplink.sh throttle` is a stub that exits 2), revocation (Phase 1), a
launchd service on macOS (the demo runs the box in a terminal on purpose, so the presenter can see it), TLS for the
tablets if Edge Server allows plain `ws://` on the LAN (decide in task 1; see Interfaces).

## Files

Owned by this workstream:
- `box/` (new: `box/edge-server/config.json.tmpl`, `box/install/install.sh`, `box/run.sh`, `box/install/uplink.sh`,
  `box/install/siab-box-agent.service` and `box/install/couchbase-edge-server.service` (Linux only, best-effort,
  omitted if the `.deb` ships a unit), `box/README.md`)
- `src/siab_box/` (new: the agent; `__main__.py`, `proxy.py`, `status.py`, `pairing.py`, `edge.py`,
  `render_config.py` or a layout of the implementer's choosing)
- `ports/box-agent.md` (new: the HTTP API below and the pairing payload)

Named edits in neighbours' code:
- `pyproject.toml`: add `siab_box` to packages, the `qrcode` (or equivalent pure-Python QR) dependency, and a
  `siab-box = "siab_box.__main__:main"` script entry.
- `ports/README.md`: append one line pointing at `ports/box-agent.md`.
- `.env.example`: append the `EDGE_*` and `SIAB_BOX_*` names below (WS2 creates the file; if WS2 has not merged,
  create it with only these names).
- `.gitignore`: add `box/.edge-server/` (the unpacked Edge Server and rendered config) and `box/logs/`.

## Interfaces

**Edge Server** (confirm every key against the Edge Server 1.1 configuration reference; the implementer writes the
template, this fixes what it must express):
- Database `retail`, scope `store`, collections `product`, `trip`, `allocation`, `transaction`, `exception`.
- Users (basic auth, `enable_user_access_control` on): `tablet-a`, `tablet-b`, `phone-1`, each with read on all
  five collections and write on `allocation`, `transaction`, `exception` (read-only on `product` and `trip`).
  Passwords from `EDGE_TABLET_A_PASSWORD`, `EDGE_TABLET_B_PASSWORD`, `EDGE_PHONE_1_PASSWORD`.
- Replication: `source` the local database, `target` the agent's counting proxy (`ws://127.0.0.1:${SIAB_PROXY_PORT}/`
  plus the endpoint path from `APP_SERVICES_PUBLIC_URL`), `bidirectional: true`, `continuous: true`, `collections`
  the five above, `auth` basic with `BOX_APP_USER`/`BOX_APP_PASSWORD`, `channels` `trip:${SIAB_TRIP}`,
  `catalog:${SIAB_REGION}`, `box:box-07`. If Edge Server refuses a plain `ws://` target or the proxy cannot
  relay the handshake, the agent measures bytes another way (see the agent's `bytes.source` field) and `uplink.sh
  cut` falls back to a null route for the App Services host (`sudo route add -host`, documented in `box/README.md`);
  the status API does not change.
- Listener: the port Edge Server uses by default (59840) unless `EDGE_PORT` is set, bound to all interfaces so the
  tablets reach it over the LAN; TLS per task 1's finding (`EDGE_TLS=on|off`). With TLS on, the agent serves the
  certificate fingerprint in the pairing payload and the PEM at `GET /cert.pem`.
- Location on the box: `install.sh` unpacks the macOS zip into `box/.edge-server/` (gitignored) and `render-config`
  writes `box/.edge-server/config.json`. Nothing is installed outside the repo checkout on macOS.

**Box agent HTTP API** (`ports/box-agent.md`), port `SIAB_BOX_PORT` default `8787`, bound to all interfaces:
- `GET /status` →
  ```json
  { "box": "box-07", "trip": "trip-2026-10-18-riverfest",
    "edge_server": { "up": true, "version": "1.1.x", "url": "wss://<lan-ip>:<port>/retail" },
    "uplink": { "reachable": true, "cut": false, "since": "<iso8601>", "target_host": "<host only, no path>" },
    "replication": { "state": "idle|busy|offline|error|unknown", "last_error": null, "checked_at": "<iso8601>" },
    "bytes": { "in": 0, "out": 0, "since": "<iso8601>", "source": "proxy|os-counter" },
    "pairing": ["tablet-a", "tablet-b", "phone-1"] }
  ```
  `uplink.reachable` is what the TCP probe to the real host says; `uplink.cut` is the software cut. They are
  independent: a pulled WAN cable gives `reachable: false, cut: false`; `uplink.sh cut` gives `reachable: true,
  cut: true`. The status page shows UPLINK CUT when either holds, and says which.
- `POST /uplink/cut` → closes every relayed upstream connection and refuses new ones (an Edge Server connection to
  the proxy is accepted and closed at once, so its replicator sees a failed connection, never a hang); returns the
  `uplink` block with `cut: true`. `POST /uplink/restore` → relaying resumes; returns `cut: false`. Both idempotent.
  Neither touches `bytes`.
- `POST /bytes/reset` → `{ "bytes": { "in": 0, "out": 0, "since": ... } }`.
- `GET /` → HTML status page: the byte counter in large type, uplink and replication state, Edge Server state,
  links to each pairing page. Polls `/status` every 2 s. No build step, no framework, one file of HTML.
- `GET /pair/<device-id>` → HTML page with the QR; `GET /pair/<device-id>.json` → the payload:
  ```json
  { "v": 1, "box": "box-07", "trip": "trip-2026-10-18-riverfest", "device": "tablet-a",
    "edge_url": "wss://192.0.2.10:59840/retail", "user": "tablet-a", "password": "<from env>",
    "cert_sha256": "<hex or null>", "peer_group": "siab-trip-2026-10-18-riverfest" }
  ```
  WS4 owns the parsing of this payload; WS3 owns its production. Served only on the LAN; the page says so.
- `GET /cert.pem` → the Edge Server certificate when `EDGE_TLS=on`, else 404.

**Counting proxy** (`SIAB_PROXY_PORT` default `8790`, bound to loopback only): accepts Edge Server's WebSocket
connection, opens TLS to the `APP_SERVICES_PUBLIC_URL` host, rewrites the `Host` header on the handshake, relays
bytes both ways and counts them. Counts are process memory, reset by `POST /bytes/reset`, and reported by
`/status`. Uplink reachability is a TCP connect to the target host every 5 s with a 2 s timeout, on a timer whose
clock is injected so tests use virtual time. The cut flag is checked on every accept and every relay write.

**CLI** (`python -m siab_box ...`): `agent` (run proxy and status server), `render-config --out PATH` (fill
`box/edge-server/config.json.tmpl` from the environment; refuses if any variable is missing), `dev` (agent only,
pointing at an Edge Server already running locally).

**`box/run.sh [--edge-only|--agent-only]`**: the way the box is started in Phase 0. Loads `.env`, renders the
config if it is missing, starts Edge Server (`box/.edge-server/couchbase-edge-server box/.edge-server/config.json`)
and `python -m siab_box agent` in the foreground, logs both to `box/logs/`, one Ctrl-C stops both, exits non-zero
if either process dies in the first 5 s. On macOS it wraps both in `caffeinate -i` so the laptop does not sleep
mid-demo.

**`box/install/install.sh`**: on macOS, downloads the Edge Server 1.1 zip for the running architecture (URL and
sha256 pinned in the script; the implementer records the sha256 from the first download), unpacks it into
`box/.edge-server/`, and checks `python` and `curl` are present. On Linux (best-effort): installs the `.deb` for the
architecture with `apt`, installs the two systemd units, enables them. The Linux branch plus the two units are
capped at about 60 lines; if the Ubuntu arm64 `.deb` needs more than that to start on Trixie, the branch prints
the manual steps and exits 2, and `box/README.md` says the Pi is unverified.

**`box/install/uplink.sh {cut|restore|status}`**: a wrapper over the agent, portable (bash and `curl` only):
`cut` and `restore` POST to `${SIAB_BOX_STATUS_URL:-http://127.0.0.1:8787}/uplink/<verb>` and print the `uplink`
block; `status` prints it. `throttle` exits 2 with "Phase 1". The physical cut needs no script: it is the router's
WAN cable, and the status page shows `reachable: false` within 10 s.

**Environment names added to `.env.example`**: `EDGE_PORT`, `EDGE_TLS`, `EDGE_TABLET_A_PASSWORD`,
`EDGE_TABLET_B_PASSWORD`, `EDGE_PHONE_1_PASSWORD`, `SIAB_BOX_PORT`, `SIAB_PROXY_PORT`, `SIAB_BOX_ID` (default
`box-07`). `APP_SERVICES_PUBLIC_URL`, `BOX_APP_USER`, `BOX_APP_PASSWORD`, `SIAB_TRIP`, `SIAB_REGION` are WS2's names;
`SIAB_BOX_STATUS_URL` (the agent's URL as seen from another machine) is WS5's and WS7's name, read here only by
`uplink.sh`.

## Contract changes

- CC1 (#2), CC4 (#5: custodian ids and channel names the config uses). No new change.

## Exit criteria

- [ ] `pytest tests/box` passes against fakes; includes `test_proxy_counts_bytes_exactly` (a fake upstream echoes a
      known payload; `in`/`out` equal its length plus the handshake bytes the test measured),
      `test_reset_zeroes_and_restamps`, `test_uplink_flips_to_unreachable_after_timeout` (virtual time),
      `test_uplink_cut_drops_relay_and_restore_resumes` (after `cut` a new proxy connection is closed at once and
      `bytes` stop growing; after `restore` relaying works and `bytes.since` is unchanged),
      `test_status_reports_cut_and_reachable_independently`, `test_pairing_payload_matches_port_doc` (fields
      exactly as in `ports/box-agent.md`), `test_render_config_refuses_missing_env`, `test_status_json_shape`.
- [ ] `python -m siab_box render-config --out /tmp/x.json` with `.env.example` names set to dummies produces valid
      JSON naming the five collections and three users.
- [ ] `[box]` On the macOS box: `box/install/install.sh` exits 0, `box/run.sh` starts both processes, and
      `curl http://127.0.0.1:8787/status` reports `edge_server.up: true` with a `version` starting `1.1`.
- [ ] `[box]` With WS2 live: `replication.state` is `idle` or `busy` and `app-services verify` (WS2) shows the box
      user's session; `POST /bytes/reset`, write one `trip` document change from HQ (WS2 `seed`), and `bytes.in`
      is greater than 0 within 30 s. Recorded in the PR (no IPs).
- [ ] `[box]` With WS2 live: `box/install/uplink.sh cut` → within 10 s `uplink.cut` is `true` and
      `replication.state` is `offline` or `error`; `uplink.sh restore` → within 30 s `replication.state` is `idle`
      or `busy` and `bytes.in` continues from its previous value (not reset). Recorded in the PR.
- [ ] `ruff check src/siab_box tests/box` prints no errors; `shellcheck box/install/*.sh box/run.sh` prints no
      errors.
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

## Owner decisions
**Answered 2026-10-07** (closing comments on #6–#11): D1 yes (all Apple devices, free Apple account, repo public, macOS CI on every PR; decision 002); D2 yes, and featured in the demo (decision 001, WS8); D3 yes; D4: the box is a macOS laptop, the Pi on Debian Trixie is best-effort (decision 002); D5 yes; D6 yes, with the event renamed Richmond Riverfest (`trip-2026-10-18-riverfest`). Money is integer cents (decision 003). The lines below are the questions as asked; anything still open is marked.


- D4 (#9): answered 2026-10-07: the macOS laptop is the supported Phase 0 box; the Pi (Debian Trixie) is optional
  and best-effort. Applied above.
- D1 (#6): answered: Python agent. Applied.
- D7 (#19): what the audience sees pulled, and where the HQ screen runs. Recommend: the travel
  router's WAN cable is the visible cut (the box laptop and the tablets stay on the router's LAN); the HQ screen
  (WS5) runs on a **second** machine with its own internet, because when the router loses its WAN so does
  everything else on the box laptop, including a browser pointed at Capella. `uplink.sh cut` is the stand-in for
  rehearsals and for a one-laptop setup. Blocks dispatch: no (the agent's cut is built either way; the answer
  changes WS7's pre-flight list, not this code).

## Verification plan

- Install, run and replicate on the macOS box: the three `[box]` exit criteria. Agent with `box`. Since D4 the box
  is a role a Mac plays, not a device: any Mac session the foreman names can be the box, but one at a time, because
  it connects as the one App Services user `box-07` and writes the one trip's data.
- **Edge Server 1.1 on the Pi (Debian Trixie, arm64)**: run `box/install/install.sh` on the Pi, then
  `curl http://localhost:59840` and `box/run.sh --edge-only`. Pass: the server answers and the config loads; the
  Pi becomes a second box for Phase 0 and the units stay. Fail: the error is recorded, the Linux branch stays as
  is and `box/README.md` marks the Pi unverified. Agent with ssh to the Pi, or the owner at the Pi. Filed as
  `needs-verification`; the owner said the Pi is optional, so if it is still open at M1 the owner moves it to M2.
- macOS application firewall: the first run prompts to allow incoming connections for the Edge Server binary and
  for Python; a tablet must reach both over the LAN afterwards. Owner-present, checked as part of WS4's pairing
  check; `box/README.md` documents the prompt.
- Byte count for "a day of fifty transactions under 100 KB": needs tablets writing transactions (WS4/WS6). Measured
  in WS7's rehearsal; the agent's counter is the instrument. Milestone audit.
- The pairing QR scans and the tablet connects: WS4's verification. Owner-present.
- The visible cut: the owner pulls the router's WAN cable and watches `uplink.reachable` flip on the status page
  within 10 s, then plugs it back and sees `replication.state` return to `idle` without a reset. Owner-present.
- Whether Edge Server accepts a plain `ws://` replication target through the proxy: task 1 finds out; if not, the
  implementer documents the fallback measurement and the null-route cut in `box/README.md`.

## Tasks

Milestones and acceptance tests (ws-design):
1. `[any]` Read the Edge Server 1.1 config and replication references; write `config.json.tmpl` and `render-config`;
   decide TLS on the LAN and record it in `box/README.md`. Accept: render-config criterion.
2. `[any]` Agent: proxy, uplink probe, cut and restore, status JSON and page, pairing pages, reset. Accept:
   `pytest tests/box`.
3. `[any]` `install.sh` (macOS first; the bounded Linux branch), `run.sh`, `uplink.sh`, the units,
   `ports/box-agent.md`, the `.gitignore` lines. Accept: `shellcheck` clean, port doc matches
   `test_pairing_payload_matches_port_doc`.
4. `[box]` On the macOS box: install and run (first `[box]` criterion); after WS2 merges, replicate to the live App
   Services and exercise the cut (second and third `[box]` criteria).
5. `[any]` **PR.** One PR, `Closes #<issue>`; `needs-verification` issues filed and linked from "Not verified"
   (expected: the Pi on Trixie, the firewall prompt, the physical cut). Expected size: about 650 lines of code
   (agent about 420, config and render about 80, scripts and units about 150; tests and fixtures not counted; split
   the issue if it is over about 1,500).

## Rules
- Code against `contracts/` and `ports/`; fake your neighbours.
- Deadline, timeout and retry tests use virtual time (a fake clock or a virtual-time event loop), not wall-clock
  sleeps: wall-clock races pass locally and flake on CI.
- Generated code is regenerated by its script, never edited by hand.
- Do not edit `contracts/` -- open a `contract-change` issue for the foreman.
- Stay inside the Files list above; an edit you need outside it gets a `for-foreman` issue first.
- Work in your own git worktree/branch `ws<N>/<topic>`; one PR per issue; CI must be green.
- Notes, questions and decision requests for the foreman: file an issue with the `for-foreman` label (see FOREMAN.md).
  Do not leave them only in PR comments.
