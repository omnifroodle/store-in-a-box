# Capella setup

How the Capella tier of Store in a Box is built: the `retail` bucket, the App Endpoint `store`, its sync functions
and app users, and the seed data. Everything is a `siab-capella` subcommand (`uv run python -m siab_capella ...`),
idempotent, with a dry run. The cluster is shared by every task that uses it (the `capella` environment in
FOREMAN.md), so read the plan before adding `--yes`.

> **Status.** The commands below are tested against `FakeCapella` and mocked HTTP only. The live run (WS2 task 3,
> `[capella]`) has not happened yet; it records here what actually happened, including any step that must be clicked
> in the Capella UI. Until then the "Manual steps" section is what the code prints, not what was observed.

## `.env`

Copy `.env.example` to `.env` at the repository root (never committed). The process environment overrides `.env`.

| Variable | What |
|---|---|
| `CAPELLA_CONN_STRING` | `couchbases://...`: the Data Service, for the SDK |
| `CAPELLA_DB_USERNAME`, `CAPELLA_DB_PASSWORD` | the cluster database credential the scripts (and WS5) use; needs read and write on `retail` and query/index rights |
| `CAPELLA_API_KEY` | Management API v4 bearer token (project owner or cluster manager, to create buckets and configure App Services) |
| `CAPELLA_API_BASE` | the Capella Management API v4 base URL (see Capella's API docs) |
| `CAPELLA_ORG_ID`, `CAPELLA_PROJECT_ID`, `CAPELLA_CLUSTER_ID` | the ids the Management API addresses |
| `CAPELLA_APP_SERVICE_ID` | the App Service linked to the cluster |
| `APP_SERVICES_PUBLIC_URL` | `wss://.../store`: the box's replication target (WS3) and what `verify` logs in to |
| `APP_SERVICES_ADMIN_URL` | the Admin REST API base, if the account exposes one (not used by the scripts yet) |
| `SIAB_TRIP`, `SIAB_REGION` | defaults: `trip-2026-10-18-riverfest`, `va-central` |
| `BOX_APP_USER`, `BOX_APP_PASSWORD` | the App Services user the box connects as (`box-07`) |
| `HQ_APP_USER`, `HQ_APP_PASSWORD` | the App Services user the HQ screen writes as (`hq`) |

Each subcommand needs only its own variables: `provision` the SDK and Management API ones, `seed` and `reset-trip`
the SDK ones, `app-services apply` the Management API ones and `CAPELLA_APP_SERVICE_ID`, `app-services verify`
`APP_SERVICES_PUBLIC_URL` and `BOX_APP_PASSWORD`. With `--dry-run` and its variables unset, a subcommand plans
offline (every step shows as `ensure`) and opens no connection.

## The commands, in order

```
uv run python -m siab_capella provision --dry-run      # read the plan
uv run python -m siab_capella provision --yes
uv run python -m siab_capella seed --diff              # live versus fixtures; writes nothing
uv run python -m siab_capella seed --yes
uv run python -m siab_capella app-services apply --dry-run
uv run python -m siab_capella app-services apply --yes
uv run python -m siab_capella app-services verify
```

Exit codes: 0 done (or planned, without `--yes`), 1 refused or failed, 2 manual steps printed. `-v` also lists the
steps already in place.

- **`provision`** creates, if missing: bucket `retail` (100 MB, the Management API's defaults otherwise), scopes
  `store`, `agents`, `ref` (the last two stay empty until their phases), the six Phase 0 collections in `store`, and
  the indexes `ix_txn_trip_unit`, `ix_txn_trip_hlc`, `ix_exc_trip_status`, `ix_alloc_trip`, `ix_inv_store`. Bucket,
  scopes and collections go through the Management API; indexes through SQL++ (`CREATE INDEX ... IF NOT EXISTS`).
- **`seed`** upserts `product::*`, `inventory::*` and `trip::*` from `contracts/fixtures/seed/` (with `--trip`, or
  `SIAB_TRIP`, only that trip). A re-seed overwrites a live edit, and editing a seed document in Capella is a
  contract change (FOREMAN.md), so run `seed --diff` first: it prints each differing field as `live -> fixture`, then
  `N differences`. The plan without `--diff` shows the same lines under each `update`.
- **`app-services apply`** works from `sync/app-endpoint.json`: creates the endpoint `store` over `retail.store`
  linking `product`, `trip`, `allocation`, `transaction`, `exception` (never `inventory`), sets each collection's
  sync function from `sync/functions/`, and creates the users `box-07` and `hq` with their channels on every linked
  collection (passwords from `.env`). It refuses when `BOX_APP_USER` names another user, or `SIAB_TRIP` /
  `SIAB_REGION` name a trip or region the box is not granted.
- **`app-services verify`** logs in to the public endpoint as the box user, prints the channels it holds per
  collection, and exits 0 when they are exactly `trip:<trip>`, `catalog:<region>`, `box:box-07` on every linked
  collection (the public channel `!` is ignored).
- **`reset-trip --trip ID --yes`** deletes the trip's `allocation`, `transaction` and `exception` documents through
  the SDK before a rehearsal (refuses without `--yes`; `--dry-run` lists them). App Services imports the deletes;
  the sync functions route the tombstones to the trip's channel so they reach the box.

## Manual steps

Where the Management API does not reach a step, `app-services apply` prints the instructions and the function body
to paste, then exits 2; do them in the Capella UI and re-run until it exits 0. What the code expects may need the
UI:

- Linking a collection to an endpoint that already exists (App Services > `store` > linked collections), which
  takes the endpoint offline until it is resumed.
- Any App Services route the Management API answers with 404, 405 or 501 (creating the endpoint, setting an access
  control function, creating or editing an app user).
- An endpoint named `store` over another bucket or scope, or a linked `inventory`: delete or unlink in the UI.

After any manual paste, re-run `apply`: it compares each live function with `sync/functions/` and reports
`unchanged` only when they match.
