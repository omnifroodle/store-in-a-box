# Port: the box agent

Owner: WS3 (`src/siab_box/`). Readers: WS4 (the tablets parse the pairing payload), WS5 (the HQ screen's box panel
reads `/status`), WS7 (the runbook drives the cut with `box/install/uplink.sh`).

The agent runs beside Couchbase Edge Server on the box. Its HTTP API listens on `SIAB_BOX_PORT` (default `8787`) on
every interface, plain HTTP, no authentication: it is meant for the venue LAN only. Every response is JSON unless
noted, with `Cache-Control: no-store`. Timestamps are RFC 3339 in UTC to the second (`2026-10-18T14:03:00Z`). Unknown
paths answer `404` with `{"error": "not found"}`.

The JSON examples below are what the tests check the agent against (`tests/box/test_port_doc.py`): same keys, same
nesting, same value types. Change this file and the agent together.

## `GET /status`

```json
{
  "box": "box-07",
  "trip": "trip-2026-10-18-riverfest",
  "edge_server": { "up": true, "version": "1.1.0", "url": "ws://192.0.2.10:59840/retail" },
  "uplink": { "reachable": true, "cut": false, "since": "2026-10-18T14:03:00Z", "target_host": "example.apps.cloud.couchbase.com" },
  "replication": { "state": "idle", "last_error": null, "checked_at": "2026-10-18T14:03:02Z" },
  "bytes": { "in": 0, "out": 0, "since": "2026-10-18T14:00:00Z", "source": "proxy" },
  "pairing": ["tablet-a", "tablet-b", "phone-1"]
}
```

- `edge_server.up`: Edge Server answered the agent's last poll (every 2 s). `version` is the vendor version from
  Edge Server's `GET /` without its build suffix (`"1.1.0"`), `null` until Edge Server has answered once. `url` is
  what the tablets replicate with: `ws://` when `EDGE_TLS=off` (the Phase 0 default), `wss://` when `on`, the box's
  LAN address, `EDGE_PORT`, database `retail`.
- `uplink.reachable`: the last TCP connect to the App Services host (every 5 s, 2 s timeout) succeeded.
  `uplink.cut`: the software cut is on. The two are independent: a pulled WAN cable gives `reachable: false, cut:
  false`; `uplink.sh cut` gives `reachable: true, cut: true`. `since` is when either last changed. `target_host` is the
  App Services host only, never its path.
- `replication.state`: one of `idle`, `busy`, `offline`, `error`, `unknown`, from Edge Server's `GET /_replicate`
  task for the App Services replication (`Idle` → `idle`, `Busy` → `busy`, `Offline` and `Connecting` → `offline`,
  `Stopped` and `Stopping` → `error`; no such task → `error`; Edge Server unreachable or unrecognised → `unknown`).
  `last_error` is Edge Server's error message for that task, or the agent's own reason, and `null` while `idle` or
  `busy`. `checked_at` is the last poll.
- `bytes`: bytes that crossed the uplink socket since `since` (the agent's start or the last reset). `out` is box to
  App Services, `in` App Services to box. `source` is `proxy` (the agent relays the replication) or `os-counter` (a
  fallback that reads the OS's interface counters, if the proxy cannot carry the replication; not built in Phase 0).
  Counts live in process memory: restarting the agent zeroes them.
- `pairing`: the device ids with a pairing page, in order.

## `POST /uplink/cut` and `POST /uplink/restore`

`cut` closes every relayed upstream connection and refuses new ones: a new connection from Edge Server is accepted and
closed at once, so its replicator sees a failed connection, never a hang. `restore` lets relaying resume. Both are
idempotent and neither touches `bytes`. Both answer with the `uplink` block:

```json
{ "uplink": { "reachable": true, "cut": true, "since": "2026-10-18T14:05:00Z", "target_host": "example.apps.cloud.couchbase.com" } }
```

## `POST /bytes/reset`

Zeroes both counts and restamps `since`:

```json
{ "bytes": { "in": 0, "out": 0, "since": "2026-10-18T14:06:00Z" } }
```

## `GET /`

The status page, one HTML file: the byte counter in large type, uplink, replication and Edge Server state, an UPLINK
CUT banner when `cut` or `!reachable` that says which, and links to each pairing page. It polls `/status` every 2 s.

## `GET /pair/<device-id>` and `GET /pair/<device-id>.json`

The HTML page shows the payload as a QR code (the payload's compact JSON is the QR's text). The `.json` form returns
the payload itself. Device ids are those in `/status` `pairing`; any other id is `404`.

### Pairing payload

```json
{
  "v": 1,
  "box": "box-07",
  "trip": "trip-2026-10-18-riverfest",
  "device": "tablet-a",
  "edge_url": "ws://192.0.2.10:59840/retail",
  "user": "tablet-a",
  "password": "from EDGE_TABLET_A_PASSWORD",
  "cert_sha256": null,
  "peer_group": "siab-trip-2026-10-18-riverfest"
}
```

- `v`: payload version, `1`. A reader refuses a version it does not know.
- `edge_url`: as `/status` `edge_server.url`.
- `user`, `password`: the device's Edge Server user (the device id) and its password from `EDGE_TABLET_A_PASSWORD`,
  `EDGE_TABLET_B_PASSWORD` or `EDGE_PHONE_1_PASSWORD`.
- `cert_sha256`: `null` when `EDGE_TLS=off`. When `on`: lower-case hex, no separators, of the sha256 of the DER
  encoding of Edge Server's certificate. The reader fetches `GET /cert.pem`, checks the fingerprint and pins it.
- `peer_group`: `siab-` plus the trip id, the device-to-device sync peer group.

WS4 owns parsing this payload; WS3 owns producing it. It carries a password: the page is served only on the LAN.

## `GET /cert.pem`

Edge Server's certificate (PEM) when `EDGE_TLS=on`, else `404`.
