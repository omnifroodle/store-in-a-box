# Port: the HQ app

Owner: WS5 (`src/siab_hq/`). Readers: WS7 (the runbook starts it and stages the oversell), WS8 (the ledger story
shows its statements), the presenter (the left half of the split screen).

The HQ app runs on the presenter's laptop against the Capella cluster: `python -m siab_hq serve [--trip ID] [--port N]`.
It listens on `127.0.0.1` only (no authentication in Phase 0), port `SIAB_HQ_PORT` (default `8788`). Every response
has `Cache-Control: no-store`; errors are `{"error": "<why>"}` with `400` (a request HQ will not write), `404` (unknown
path, trip or dispute), `405` or `500` (Capella unreachable). Timestamps are RFC 3339 in UTC to the second. Every
endpoint takes `trip` (query parameter for a `GET`, body field for a `POST`); it defaults to the served trip
(`--trip`, else `SIAB_TRIP`).

All reads and writes go through WS2's `CapellaGateway` (`ports/capella.md`) as the cluster database credential, and
the ledger is WS1's `siab_ledger` (`ports/ledger.md`). HQ's view is live, never settled (decision 007): the screen
says `trip open: live view, nothing settled`, and closes are Phase 2.

The JSON examples below are what `tests/hq/test_port_doc.py` checks the app against: same keys, same nesting, same
value types. Change this file and the app together.

## Environment

`SIAB_HQ_PORT` (default `8788`), `SIAB_BOX_STATUS_URL` (optional: the box agent's `/status`, `ports/box-agent.md`),
`SIAB_RECONCILE_INTERVAL_S` (default `3`), `SIAB_TRIP`, and the `CAPELLA_DB_*` credential with `CAPELLA_CONN_STRING`.
`SIAB_HQ_FAKE=<ledger fixture name or path>` (for example `oversell-hq`) runs against WS2's `FakeCapella` loaded with
that fixture's transactions, resolutions and inventory and the seed's trips and products, instead of Capella.

## `GET /api/conservation?trip=[&sql=1]`

```json
{
  "trip": "trip-2026-10-18-riverfest",
  "as_of": "2026-10-18T14:03:00Z",
  "rows": [
    { "sku": "HAT-BRIM-OS", "opening_on_hand": 2, "received": 0, "left_store": 3, "untraced": 0,
      "returned_to_store": 0, "store_on_hand": -1, "in_custody": { "box-07": 2 }, "sold": 1, "disputed": 0,
      "holds": false }
  ],
  "holds": false
}
```

`rows` are `siab_ledger.conservation` with the store's inventory, WS1's row shape (`ports/ledger.md`, "Conservation");
`holds` is true only when every row's is. `as_of` is the reconciler's last read. With `sql=1` the reply also has
`statements`: the SQL++ run, each `{ "statement", "params" }`:

- `SELECT META(t).id AS _id, t.* FROM retail.store.transaction AS t WHERE t.trip = $trip ORDER BY t.hlc`
- `SELECT META(e).id AS _id, e.* FROM retail.store.exception AS e WHERE e.trip = $trip`
- `SELECT META(i).id AS _id, i.* FROM retail.store.inventory AS i WHERE i.store = $store`
- `SELECT META(a).id AS _id, a.* FROM retail.store.allocation AS a WHERE a.trip = $trip`

(every keyspace part backquoted, `transaction` being a reserved word; `$store` is the trip document's `store`).

On screen, a row that does not hold is highlighted and its reason cell says why: `overdrawn by N` when
`store_on_hand < 0` (`N = -store_on_hand`), `N untraced` when `untraced > 0`, both comma-separated when both apply;
a row that holds has an empty reason cell. The indicator reads `HOLDS · live`, or `N SKUs do not hold · live`. Nothing
is written for a failing row (an exception per SKU is Phase 2's Eventing).

## `GET /api/tree?trip=`

```json
{
  "root": "store-richmond",
  "nodes": [
    { "custodian": "store-richmond", "parent": null, "allocations": [], "held": { "JKT-RAIN-M-BLU": 1 } },
    { "custodian": "box-07", "parent": "store-richmond",
      "allocations": [ { "id": "alloc::1792328400000-0000-tablet-a", "sku": "JKT-RAIN-M-BLU", "status": "active", "count": 5 } ],
      "held": { "JKT-RAIN-M-BLU": 5 } }
  ]
}
```

One node per custodian that holds a unit or has an allocation, the store first, then breadth-first by parent. An
allocation's `count` is the reducer's `allocation_counts` (held units in it, zeros included); `status` is the
allocation document's, `null` when only transactions name it. A node's `parent` is the `from_custodian` of its
allocation, else the trip's box for a trip device, else the store. `held` is the reducer's `counts` for that holder.

## `GET /api/exceptions?trip=&status=open|resolved|all`

```json
{
  "disputes": [
    {
      "dispute_key": "JKT-RAIN-M-BLU#001|root",
      "kind": "oversell",
      "unit_id": "JKT-RAIN-M-BLU#001",
      "sku": "JKT-RAIN-M-BLU",
      "detectors": ["hq", "tablet-a"],
      "transactions": [ { "_id": "txn::1792328410000-0000-tablet-a" } ],
      "branches": [ { "txn": { "_id": "txn::1792328410000-0000-tablet-a" }, "leaf": { "_id": "txn::1792329000000-0000-tablet-a" } } ],
      "documents": [ { "_id": "exc::hq::JKT-RAIN-M-BLU#001::57cf515b" } ],
      "status": "open",
      "label": "open",
      "resolution": null
    }
  ],
  "superseded": [ { "_id": "exc::hq::JKT-RAIN-M-BLU#005::d7a5d96d" } ]
}
```

(Transaction and exception documents are shortened to `_id` here; the reply carries them whole.)

The queue is the reducer's, not the documents' (decisions 008 and 009), and `status` filters by the entry's state,
not a document's. A fork entry is one per `(dispute_key, transactions)`: a fork binds to its branch set (decision
006). An unexpected check-in or foreign movement entry is one per `(kind, dispute_key)`: the key names the movement,
and its attached set grows when a predecessor arrives, so a closure holds for the movement whatever it attached. A fork
at a flagged movement shares the movement's `dispute_key` and is a separate entry (its `kind` is a fork's).

- `open`: each fork in `forks` with `resolved_by` null, and each unexpected check-in or foreign movement not set
  aside that no counting resolution of that `kind` and `dispute_key` has closed. `resolved`: each fork a resolution
  settled, and each such movement a counting resolution closed.
- `label`: `open`; `withdrawn: choose again` (an open fork that a counting resolution matches: HQ's latest word chose
  nothing); `open: HQ's copy on the next run` (no document yet; the reconciler writes HQ's); `resolved`.
- `resolution`: the deciding resolution block of a resolved entry, else `null`.
- `transactions`: the full documents of the set (for a movement: the movement and, when HQ has it, its predecessor).
  `branches[i].leaf`: the last canonical movement of that branch (the greatest `hlc` when it splits again); in the
  staged oversell the pack branch's leaf is the tablet's sale.
- `documents`: every exception document of the entry, any detector, any status: for a fork those with its
  `dispute_key` and exact set, for a movement every copy of that `kind` and `dispute_key` whatever its `transactions`.
- `superseded`: open documents that match no entry (a fork that vanished when a return arrived, a two-branch copy
  after a third branch, anything inside a set-aside branch). Not counted; `close-superseded` closes them.

## `POST /api/exceptions/resolve`

Body `{ "trip", "dispute_key", "transactions", "chosen_txn", "note" }`. Sets `status: "resolved"` and
`resolution: { "by": "hq", "hlc", "at", "chosen_txn", "note" }` on every copy of the dispute, whatever its detector
or status:

- a fork (`transactions` does not hold the movement the `dispute_key` names: a fork's branches never hold their
  predecessor): the documents with that `dispute_key` whose `transactions` equal the given set; copies written for
  another set stay as they are (decision 006). `chosen_txn` must be one of `transactions`.
- an unexpected check-in or a foreign movement (`transactions` holds the movement): every `unexpected_check_in` or
  `foreign_movement` document with that `dispute_key`, whatever its `transactions` (decision 009). `chosen_txn` is
  null.

Anything else is `400`. When nothing matches yet, the reconciler runs first (writing HQ's own copy of a live
dispute); still nothing is `404`. HQ writes no `check_out`: rule 8 gives `hq` no box (`foreign-hq-check-out`).

```json
{ "updated": 2, "hlc": "1792330800000-0000-hq" }
```

`resolution.hlc` is HQ's clock and orders HQ's decisions (decision 008); `at` is a label. HQ keeps one HLC for device
`hq`: `hlc_now(clock, last, "hq")`, `last` being the greater of the last it issued and the greatest it has read (every
`resolution.hlc` among the trip's exceptions, and every transaction's `hlc` and exception's `detected_at`), so it is
monotonic across restarts without a file, and what HQ writes comes after everything it has seen (the staged sale is
the later branch of its fork even when the laptop's clock is behind the tablets').

## `POST /api/exceptions/close-superseded`

Body `{ "trip" }`. Resolves every `superseded` document with `chosen_txn` null and note `superseded`, one HQ HLC for
the batch. It matches no dispute, so it settles and withdraws nothing.

```json
{ "updated": 1 }
```

## `POST /api/stage/hq-sale`

Body `{ "trip", "unit_id", "price"? }`. The staged oversell: writes one `transaction` as device `hq`, `kind: "sale"`,
`from_custodian` the trip's store, `to_custodian: "customer"`, `prev_txn: null`, `box: null`, `basket` a new UUID,
`price` the body's (`{ "cents", "currency": "USD" }`) or the product's, `tender: { "kind": "card_simulated", "amount" }`.
Only a unit the ledger shows as held by the trip's box or one of its devices may be sold (`400` otherwise; `GET
/api/stage/units` lists them). HQ acts for the store, so the sale is not foreign (rule 8); with the pack it is a root
fork, and the reconciler writes one `oversell` for it.

```json
{ "id": "txn::1792329100000-0000-hq" }
```

## `GET /api/stage/units?trip=`

```json
{ "units": [ { "unit_id": "JKT-RAIN-M-BLU#001", "sku": "JKT-RAIN-M-BLU", "holder": "box-07" } ] }
```

## `GET /api/box`

The box agent's `GET /status` (`ports/box-agent.md`) as it answered, when `SIAB_BOX_STATUS_URL` is set. Unset:

```json
{ "configured": false }
```

Set but unreachable: `502` with `{ "configured": true, "reachable": false, "error": "<why>" }`.

## `GET /api/reconcile/status` and `POST /api/reconcile/run`

```json
{ "last_run": "2026-10-18T14:03:00Z", "exceptions_written": 1, "forks_open": 1, "last_error": null }
```

`exceptions_written` counts since the app started; `forks_open` is the last run's; `last_error` is the last failed
run's error, `null` after a run succeeds. `POST /api/reconcile/run` runs the reconciler once and answers the same.

## The reconciler

At startup, every `SIAB_RECONCILE_INTERVAL_S` and on `POST /api/reconcile/run`: read the trip (the statements above),
`state = reduce(transactions, exceptions, store)`, `exceptions_for(state, "hq", trip, None)` stamped with HQ's HLC
as `detected_at`, and upsert only the documents whose id does not exist. Idempotent by id. `python -m siab_hq reconcile
--once [--trip ID] [--dry-run]` runs it once and prints `wrote <id>` (or `would write <id>`) per document.

## The screen and its panels

`GET /` is the screen (`static/index.html`, `hq.js`, `hq.css`; no build step): conservation, custody tree,
exceptions with resolve, the stage control and the box panel. It polls `GET /panels/<name>?trip=` every 2 s for
`conservation`, `tree`, `exceptions` (with `status`), `stage` and `box`: the same views rendered as HTML fragments,
so the server renders every word on screen once.
