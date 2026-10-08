# WS2: Capella, App Services and the sync function

**Milestone:** M1  **Depends on:** contracts v0.1 (CC1, CC2, CC4)  **Label:** `ws:2-capella-sync`  **Agent type:** ws-design
**Issue:** #13

The blueprint. The architect (`ws-architect`) writes it before any code is dispatched; the PR is judged against it.

## Scope

The cloud tier for Phase 0: the `retail` bucket with its scopes and the Phase 0 collections, the App Services App
Endpoint over scope `store`, one sync function per synced collection (short enough to put on screen), the app users
the box and the HQ screen connect as, the seed data derived from the contract fixtures, and the indexes the HQ
queries need. Everything is a script that is idempotent and has a dry run, because the cluster is a single-instance
environment (`capella`) that other tasks share.

Built here:
- `siab_capella`: a Python CLI over the Couchbase SDK and the Capella Management API. `provision` (bucket, scopes,
  collections, indexes), `seed` (products, inventory, trip from `contracts/fixtures/seed/`, with `--diff`),
  `app-services apply|verify` (endpoint, collections, users, sync functions), `reset-trip` (clear a trip's venue
  documents before a rehearsal).
- `sync/`: the sync functions, one JavaScript file per collection, and a Node test harness that runs them against
  `contracts/fixtures/sync/`.
- `docs/capella-setup.md`: what the scripts do, what must still be clicked in the Capella UI (if anything), the
  `.env` variables.

Left for later: `inventory` on-hand maintenance by Eventing (Phase 2; Phase 0 derives on-hand in the conservation
query), `customers:<region>` and `product_venue` filtering (Phase 1), roles instead of per-user channels, OIDC,
revocation drill (Phase 1), `agents` and `ref` collections (their schemas arrive with their phases; `provision`
creates the two scopes empty).

## Files

Owned by this workstream:
- `src/siab_capella/` (new: the CLI and its gateway port; `__main__.py`, `provision.py`, `seed.py`,
  `app_services.py`, `gateway.py` with the `CapellaGateway` protocol and `FakeCapella`)
- `sync/` (new: `sync/functions/store.product.js`, `store.trip.js`, `store.allocation.js`, `store.transaction.js`,
  `store.exception.js`; `sync/app-endpoint.json`; `sync/tests/harness.mjs`, `sync/tests/fixtures.test.mjs`;
  `sync/README.md`)
- `docs/capella-setup.md` (new)
- `ports/capella.md` (new: the gateway port and the environment variable names; the line in `ports/README.md`)

Named edits in neighbours' code:
- `pyproject.toml`: add `siab_capella` to packages, the `couchbase` and `httpx` dependencies, and a
  `siab-capella = "siab_capella.__main__:main"` script entry.
- `ports/README.md`: append one line pointing at `ports/capella.md`.
- `.env.example` (new file at the repo root, no values): the variable names below.

## Interfaces

**`.env` variables** (names are the contract; values never committed; the foreman copies these into FOREMAN.md):
```
CAPELLA_CONN_STRING        couchbases://... (Data Service, SDK)
CAPELLA_DB_USERNAME        cluster database credential used by the scripts and WS5
CAPELLA_DB_PASSWORD
CAPELLA_API_KEY            Capella Management API v4 bearer token
CAPELLA_ORG_ID
CAPELLA_PROJECT_ID
CAPELLA_CLUSTER_ID
CAPELLA_APP_SERVICE_ID
APP_SERVICES_PUBLIC_URL    wss://.../<endpoint>  (the box's replication target; WS3 reads it)
APP_SERVICES_ADMIN_URL     https://...           (Admin REST API base, if the account exposes one)
SIAB_TRIP                  default trip id, e.g. trip-2026-10-18-riverfest
SIAB_REGION                default catalog region, e.g. va-central
BOX_APP_USER / BOX_APP_PASSWORD      App Services user the box connects as (default user name: box-07)
HQ_APP_USER  / HQ_APP_PASSWORD       App Services user the HQ screen writes as (default: hq)
```

**Names** (from CC2 and CC4): bucket `retail`; scopes `store`, `agents`, `ref`; Phase 0 collections in `store`:
`product`, `inventory`, `trip`, `allocation`, `transaction`, `exception`. App Endpoint `store` over scope `store`,
linking `product`, `trip`, `allocation`, `transaction`, `exception` (never `inventory`). Channels: `trip:<trip-id>`,
`catalog:<region>`, `box:<box-id>`. App users: `box-07` with channels `trip:<SIAB_TRIP>`, `catalog:<SIAB_REGION>`,
`box:box-07` on every linked collection; `hq` with `*`.

**Sync function rules**, one file per collection, each `function (doc, oldDoc, meta) { ... }`. These are the
contract the Node harness tests against `contracts/fixtures/sync/`; the implementer writes the JavaScript.
- Common: `doc.type` must equal the collection name or `throw({forbidden: "type mismatch"})`. Deletes
  (`doc._deleted`) are allowed only for user `hq`.
- `product`: writer must be `hq`; `doc.regions` is a non-empty array; `channel("catalog:" + r)` for each region.
- `trip`: writer must be `hq`; `channel("trip:" + doc.trip_id)` and `channel("box:" + doc.box)`.
- `allocation`: `doc.trip` and `doc.box` required; writer is `hq` or `meta.user.name === doc.box`
  (`requireUser([doc.box, "hq"])`); `requireAccess("trip:" + doc.trip)`; on update, only `status` and `closed_at`
  may change (compare every other field to `oldDoc`); `channel("trip:" + doc.trip)`.
- `transaction`: same writer and access rules; **immutable**: any update (`oldDoc` not null) is forbidden;
  `hq`-written transactions may carry `box: null`; `channel("trip:" + doc.trip)`.
- `exception`: same writer and access rules on create; on update only `hq` may write and only `status` and
  `resolution` may change; `channel("trip:" + doc.trip)`.

**Node harness** (`sync/tests/harness.mjs`): loads a function file, provides `channel`, `requireUser`,
`requireAccess`, `requireRole`, `access`, and turns `throw({forbidden})` into a result. Each fixture case
`{collection, user: {name, channels}, doc, oldDoc, expect: {ok, channels?, error?}}` is one test. Run with
`node --test sync/tests/`.

**`app-endpoint.json`**: the declarative description `app-services apply` works from: endpoint name, bucket,
scope, linked collections, per-collection sync function path, users and their channels. One file, no secrets
(passwords come from `.env`).

**CLI** (`python -m siab_capella ...`, every subcommand accepts `--dry-run` and prints its plan; nothing writes
without `--yes` except `verify` and `--diff`):
- `provision [--yes]`: bucket (if missing), scopes `store`/`agents`/`ref`, the six Phase 0 collections, indexes
  `ix_txn_trip_unit` on `transaction(trip, unit_id, hlc)`, `ix_txn_trip_hlc` on `transaction(trip, hlc)`,
  `ix_exc_trip_status` on `exception(trip, status)`, `ix_alloc_trip` on `allocation(trip, custodian, status)`,
  `ix_inv_store` on `inventory(store, sku)`. Idempotent.
- `seed [--trip ID] [--diff] [--yes]`: upserts `product::*`, `inventory::*`, `trip::*` from
  `contracts/fixtures/seed/`; `--diff` prints live-vs-fixture differences and writes nothing (FOREMAN.md: a
  re-seed overwrites a live edit, so diff first).
- `app-services apply [--yes]`: creates or updates the endpoint, links collections, sets each collection's sync
  function from `sync/functions/`, creates users with channels. Where the Management API does not cover a step,
  print the exact manual steps and the function body to paste, and exit 2.
- `app-services verify`: connects to `APP_SERVICES_PUBLIC_URL` as `box-07`, confirms the session, lists the
  channels granted per collection, exits 0 on the expected set.
- `reset-trip --trip ID --yes`: deletes `allocation`, `transaction` and `exception` documents for the trip through
  the SDK as `hq`. Refuses without `--yes`.

**Gateway port** (`ports/capella.md`): `CapellaGateway` protocol with the handful of operations the CLI uses
(`ensure_bucket`, `ensure_scope`, `ensure_collection`, `ensure_index`, `upsert`, `get`, `query`, `delete`,
`app_services_*`), and `FakeCapella` recording calls for the unit tests. WS5 uses the same protocol for its reads.

## Contract changes

- CC1 (#2): layout and validator.
- CC2 (#3): `store.product`, `store.inventory`, `store.trip` schemas and the seed fixtures.
- CC4 (#5): custodian registry, channel names and the sync fixtures under `contracts/fixtures/sync/`.

## Exit criteria

- [ ] `node --test sync/tests/` passes every case in `contracts/fixtures/sync/`.
- [ ] `pytest tests/capella` passes against `FakeCapella`; includes `test_provision_is_idempotent` (second run plans
      zero changes), `test_seed_diff_reports_live_edit`, `test_reset_trip_refuses_without_yes`,
      `test_app_endpoint_json_matches_fixture_users` (users and channels in `sync/app-endpoint.json` equal those in
      `contracts/fixtures/seed/custodians.json`).
- [ ] `python -m siab_capella provision --dry-run` and `seed --dry-run` print a plan and exit 0 with only
      `.env.example` values set (no network).
- [ ] `[capella]` `python -m siab_capella provision --yes && python -m siab_capella seed --yes && python -m siab_capella
      app-services apply --yes && python -m siab_capella app-services verify` exits 0 on the live cluster, and a
      second `seed --diff` prints "0 differences". Recorded in the PR with the command output (no hostnames).
- [ ] `ruff check src/siab_capella tests/capella` prints no errors.
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

## Owner decisions
**Answered 2026-10-07** (closing comments on #6–#11): D1 yes (all Apple devices, free Apple account, repo public, macOS CI on every PR; decision 002); D2 yes, and featured in the demo (decision 001, WS8); D3 yes; D4: the box is a macOS laptop, the Pi on Debian Trixie is best-effort (decision 002); D5 yes; D6 yes, with the event renamed Richmond Riverfest (`trip-2026-10-18-riverfest`). Money is integer cents (decision 003). The lines below are the questions as asked; anything still open is marked.


- D1 (#6): stack (Python for tooling, JavaScript for the sync function, Node for its tests). Answered: yes.
- D6 (#11): demo names and seed values (trip id, store, box, region, prices, tender kinds). Blocks dispatch: no;
  the defaults in CC2 apply if unanswered.

## Verification plan

- Live provisioning and App Services configuration on the owner's cluster: the `[capella]` exit criterion above.
  Agent with `capella`. If the Management API cannot set per-collection sync functions or users, the agent follows
  the printed manual steps and the owner confirms the pasted function matches `sync/functions/` (owner, with the
  Capella UI open); filed as `needs-verification` if left open.
- Sync function behaviour on the real App Services runtime (the Node harness is a fake of it): after WS3 is live,
  push one transaction as `box-07` with the wrong `box` and confirm a 403 in the Edge Server replication status.
  Agent with `capella` and `box`, or the milestone audit.
- Channel grants: `app-services verify` output. Agent with `capella`.

## Tasks

Milestones and acceptance tests (ws-design):
1. `[any]` Sync functions and the Node harness. Accept: every `contracts/fixtures/sync/` case passes.
2. `[any]` `siab_capella` CLI over `CapellaGateway` with `FakeCapella`; `app-endpoint.json`; `.env.example`;
   `ports/capella.md`. Accept: the `pytest tests/capella` criteria and the dry runs.
3. `[capella]` Provision, seed and apply on the live cluster; `verify` green; `docs/capella-setup.md` written from
   what actually happened (including any manual step). Accept: the `[capella]` exit criterion.
4. `[any]` **PR.** One PR, `Closes #<issue>`; `needs-verification` issues filed and linked from "Not verified".
   Expected size: about 900 lines of code (tests and fixtures not counted; split the issue if it is over about
   1,500).

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
