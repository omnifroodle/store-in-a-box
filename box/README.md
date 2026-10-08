# The box

Couchbase Edge Server 1.1 on the macOS laptop that is the Phase 0 box, and beside it the box agent
(`src/siab_box/`): the counting proxy every uplink byte goes through, the status page, and the pairing QR codes.
The box runs no custody logic: it moves documents. The agent's HTTP API is in [`ports/box-agent.md`](../ports/box-agent.md).

```
box/
  edge-server/config.json.tmpl   the Edge Server config, filled from .env by render-config
  install/install.sh             downloads and unpacks Edge Server (macOS); the .deb and units (Linux, best-effort)
  install/uplink.sh              cut | restore | status | throttle (Phase 1) the software uplink
  install/*.service              Linux only: systemd units for the Pi
  run.sh                         starts Edge Server and the agent in the foreground
  .edge-server/                  (gitignored) the unpacked server, rendered config, users file, database
  logs/                          (gitignored) one log per process per run
```

## Run it

1. `uv sync`, then fill in `.env` (names in `.env.example`; WS2's Capella names plus the box's `EDGE_*` and
   `SIAB_BOX_*`).
2. `box/install/install.sh`: downloads the Edge Server 1.1.0 macOS zip from packages.couchbase.com, checks it against
   the vendor's published sha256, and unpacks it into `box/.edge-server/`. Nothing is installed outside the checkout.
3. `box/run.sh`: renders `box/.edge-server/config.json` if it is missing, starts Edge Server and the agent, and keeps
   the laptop awake (`caffeinate -i`). Both logs stream to the terminal and to `box/logs/`. One Ctrl-C stops both; it
   exits non-zero if either dies. `--edge-only` and `--agent-only` start one of them.
4. The status page is `http://<box>:8787/`; each device pairs from `http://<box>:8787/pair/<device>`.

Changed a password or a port in `.env`? `uv run python -m siab_box render-config` and restart `run.sh`.
`uv run python -m siab_box dev` runs the agent alone against an Edge Server you started yourself, with placeholders
for whatever is unset.

**First run: the macOS firewall.** If the application firewall is on, macOS asks once whether
`couchbase-edge-server` and `python3` may accept incoming connections. Allow both: the tablets reach Edge Server
(port 59840) and the pairing page (port 8787) over the LAN.

## What task 1 found in the Edge Server 1.1 configuration reference

Checked against <https://packages.couchbase.com/couchbase-edge-server/config_schema.json> and the Edge Server docs
(authentication, REST API, replication), October 2026.

- **Collections are named `scope.collection`** (`store.product`), in the database's `collections` list and as the
  keys of the replication's `collections` object. Channels are per collection in that object: a top-level
  `channels` key is not allowed alongside `collections`.
- **Users live in a separate file** (`users` is a path), as bcrypt hashes: there is no `enable_user_access_control`
  key; every request needs a user unless `enable_anonymous_users` is true (it is false here). render-config hashes
  the three device passwords with `htpasswd -B` (password on stdin; pre-installed on macOS, `apache2-utils` on Linux)
  and writes `users.json` beside the config.
- **No per-collection privileges.** Edge Server 1.1 has two roles, `replicate` and `admin`, and they govern the REST
  replication API, not documents. A user that can sync can read and write every shared collection; the only knob is
  per database (`enable_client_sync`: `pull`, `push` or `bidirectional`). So the blueprint's "read-only on `product`
  and `trip`" for the devices cannot be expressed on the box; the App Services sync function still rejects a box
  write to `product` or `trip` on the way up (`contracts/fixtures/sync/product-by-box-forbidden.json`).
- **The agent has its own Edge Server user**, `siab-agent` with role `replicate`, so it can read `/_replicate`.
  render-config gives it a random password and writes it to `box/.edge-server/agent.json` (mode 0600). It is not in
  `.env`.
- **A plain `ws:` replication target is allowed**: "the other must be a remote ws: or wss: sync URL". So the
  replication's target is the agent's proxy on loopback, `ws://127.0.0.1:8790/<endpoint>`, and the agent opens the
  TLS connection to App Services. Not yet seen working against the live App Endpoint (task 4).
- **Replications also take a `proxy` setting** (HTTP CONNECT). The agent accepts CONNECT too, for the App Services
  host and port only. If the `ws:` target misbehaves on the box, switch the replication to the real
  `APP_SERVICES_PUBLIC_URL` as `target` plus `"proxy": {"type": "HTTP", "host": "127.0.0.1", "port": 8790}`: Edge
  Server then keeps its own TLS end to end, the agent still counts (TLS bytes, so a little more) and still cuts. The
  status API does not change.
- The database file is `box/.edge-server/retail.cblite2`, `create: true`. Whether `create` also creates the scope
  and the five collections on first start is checked in task 4.

## TLS on the LAN: off for Phase 0 (`EDGE_TLS=off`)

Edge Server serves plain HTTP and `ws://` unless the config has an `https` block, so the blueprint's rule applies:
TLS for the tablets is left for later. The tablets replicate to `ws://<box>:59840/retail`.

Why off: the venue LAN is the travel router's own WPA2 network; Phase 0 carries no customer data; and a self-signed
certificate whose name is the box's DHCP address adds a pinning step to every pairing and a failure mode to every
venue. The cost, which the Edge Server docs warn about: the devices' basic-auth passwords cross the LAN in clear.
They are demo passwords that open nothing but this box.

`EDGE_TLS=on` is built and is the setting for Phase 1: `run.sh` makes a self-signed certificate with
`couchbase-edge-server --create-cert CN=<lan ip>`, render-config adds the `https` block, `edge_url` becomes `wss://`,
the pairing payload carries `cert_sha256`, and the agent serves the PEM at `/cert.pem` for the tablet to pin.

## Cutting the uplink

Edge Server cannot tell the two cuts apart: a connection drops, retries fail, and it resumes from its checkpoint when
the link is back.

- **Software cut (the default, one laptop).** `box/install/uplink.sh cut`: the agent closes every relayed connection
  and refuses new ones, so the replicator goes offline at once. The laptop keeps its internet, so an HQ screen on the
  same laptop stays live and shows Capella receiving nothing. `uplink.sh restore` resumes; the byte count carries on.
  From another machine, set `SIAB_BOX_STATUS_URL=http://<box>:8787`.
- **Physical cut (the alternative).** Pull the travel router's WAN cable, with the HQ screen on a second machine that
  has its own internet. The status page shows UPLINK CUT, "App Services unreachable", within 10 s (a TCP probe every
  5 s, 2 s timeout).
- **Fallback, if the proxy cannot carry the replication at all:** point the replication straight at
  `APP_SERVICES_PUBLIC_URL` and cut with a null route for the App Services host,
  `sudo route add -host <app services ip> 127.0.0.1 -blackhole` (`sudo route delete -host <ip>` to restore). The
  agent then cannot count bytes; `bytes.source` stays `proxy` and the count stays at 0. Counting from the OS's
  interface counters (`os-counter`) is not built.

## The Raspberry Pi: unverified

The owner's Pi runs Debian Trixie, which Edge Server 1.1 does not list for ARM64 (Ubuntu 22.04+ only). On Linux,
`install.sh` installs the vendor's arm64 or amd64 `.deb` (checked against its published sha256), `apache2-utils` for
`htpasswd`, and the two units in `install/`, which take the place of the package's own unit. If the package does not
install cleanly it prints the manual steps and exits 2. Nothing in Phase 0 depends on the Pi; whether Edge Server
runs on Trixie arm64 is an open verification item.
