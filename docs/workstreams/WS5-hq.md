# WS5: HQ screen, the conservation query and the Capella-side reconciler

**Milestone:** M1  **Depends on:** WS1, WS2  **Label:** `ws:5-hq`  **Agent type:** ws-design
**Issue:** #16

The blueprint. The architect (`ws-architect`) writes it before any code is dispatched; the PR is judged against it.

## Scope

The left half of the split screen. A small web app the presenter runs on the laptop against the Capella cluster:
the **conservation table** per SKU (store on-hand, units in custody per custodian, sold, disputed, and whether the
invariant holds), the **custody tree** (store, box, tablets, with counts), the **exception queue** grouped by
dispute, with resolve; a control to **stage the HQ oversell** (a sale at the flagship of a unit the box holds); and
an optional panel mirroring the box's byte counter. Behind it, the **reconciler**: a loop that reads the trip's
transactions and exceptions, runs the WS1 ledger, writes an `exception` for every unresolved fork as detector
`hq`, and serves the conservation rows. The cloud reads the result; it adjudicates nothing.

Left for later: Eventing for exception routing and reorder (Phase 2), the reconciliation explainer (Phase 2), the
permit queue (Phase 2), the `_changes` feed instead of polling, authentication on the HQ app (it binds to loopback
in Phase 0), and an `exception` document for a conservation row that does not hold (the spec gives that to
Eventing in Phase 2; the `exception` schema is per unit and has no kind for a per-SKU gap). In Phase 0 the screen
shows the failing row; nothing is written.

## Files

Owned by this workstream:
- `src/siab_hq/` (new: `__main__.py`, `server.py`, `reconcile.py`, `queries.py`, `static/index.html`,
  `static/hq.js`, `static/hq.css`)
- `ports/hq.md` (new: the HTTP API below)

Named edits in neighbours' code:
- `pyproject.toml`: already declares `siab_hq` and the `siab-hq` script (M0 setup PR). Edit it only to add the web
  framework dependency if one is used (stdlib `http.server` plus `asyncio` is acceptable and preferred).
- `ports/README.md`: append one line pointing at `ports/hq.md`.
- `.env.example`: append `SIAB_HQ_PORT` (default `8788`), `SIAB_BOX_STATUS_URL` (optional, the box agent's
  `/status`), `SIAB_RECONCILE_INTERVAL_S` (default `3`).

## Interfaces

**Reads and writes go through WS2's `CapellaGateway`** (`ports/capella.md`); tests use `FakeCapella` loaded with
the ledger fixtures' transactions. The ledger is `siab_ledger` (WS1), imported, never re-implemented.

**SQL++ the HQ runs** (fixed in shape, tuned by the implementer; uses WS2's indexes):
- Transactions for a trip: `SELECT t.* FROM retail.store.transaction t WHERE t.trip = $trip ORDER BY t.hlc`.
- Exceptions for a trip: `SELECT e.* FROM retail.store.exception e WHERE e.trip = $trip`.
- Inventory for the trip's store: `SELECT i.* FROM retail.store.inventory i WHERE i.store = $store`.
- The conservation rows are computed by `siab_ledger.conservation` from those three result sets. The query the
  presenter puts on screen is the one above plus the Python that folds it; `GET /api/conservation?sql=1` returns
  the exact statements run, so the demo can show them.

**HTTP API** (`ports/hq.md`), `SIAB_HQ_PORT` default `8788`, loopback only:
- `GET /` → the screen: three panels (conservation, tree, exceptions), the stage control, the optional box panel.
  Polls every 2 s. Plain HTML, one JS file, no build step.
- `GET /api/conservation?trip=` → `{ "trip": ..., "as_of": iso8601, "rows": [ConservationRow...], "holds": bool }`
  where `ConservationRow` is WS1's shape: `sku, opening_on_hand, received, left_store, untraced,
  returned_to_store, store_on_hand, in_custody{custodian: n}, sold, disputed, holds` (`contracts/fixtures/README.md`,
  CC5 #29), always computed with the inventory, and the top-level `holds` is true only when every row's is. A
  row fails for one of two reasons the row itself carries, and the screen says which: `store_on_hand < 0`
  (overdrawn: the ledger names more units than the store had) or `untraced > 0` (units nothing traces to the
  store). On screen a failing row is highlighted and gets a reason cell, byte for byte `overdrawn by N`
  (`N = -store_on_hand`) or `N untraced` (both, comma-separated, when both apply); the "holds" indicator at the
  top of the panel reads `HOLDS` when every row holds and `N SKUs do not hold` otherwise. A row that holds has an
  empty reason cell. Nothing is written for a failing row (see "Left for later").
- `GET /api/tree?trip=` → `{ "root": "store-richmond", "nodes": [ { "custodian", "parent", "allocations": [ { "id",
  "sku", "status", "count" } ] } ] }` built from `LedgerState.allocation_counts` and the allocation documents.
- `GET /api/exceptions?trip=&status=open|resolved|all` → `{ "disputes": [...], "superseded": [...] }`. **The queue is
  the reducer's, not the documents'** (#77 finding F, decision 008): one entry per `(dispute_key, transactions)` that
  HQ's own `reduce` holds as a live dispute (each fork in `forks` with `resolved_by` null, and each unexpected check-in
  or foreign movement not set aside and not matched by a counting resolution), each with `"dispute_key", "kind",
  "unit_id", "sku", "detectors", "transactions"` (full docs), `"branches": [ { "txn", "leaf" } ]` (the leaf is the full
  doc of the branch's last movement), `"documents"` (every exception doc with that key and set, any detector, any
  status) and `"status"`. An entry whose documents are all resolved with `chosen_txn` null reads `withdrawn: choose
  again`; one with no document yet gets HQ's own on the reconciler's next run. Open documents that match no live dispute
  (a fork that vanished when a return arrived, a two-branch copy after a third branch, anything inside a set-aside
  branch) are listed under `superseded`, not counted, and may be bulk-closed with `chosen_txn` null and note
  `superseded`. `status` filters by the entry's state, not the document's. The dispute view shows each branch's leaf as
  well as the branch movement (in the staged oversell the tablet's sale is the pack branch's leaf, #61);
  `foreign_movement` renders like `unexpected_check_in` (the movement and its predecessor, "did not hold it").
- `POST /api/exceptions/resolve` body `{ "trip", "dispute_key", "transactions", "chosen_txn", "note" }` (#72 item 3) →
  updates only the exception documents with that `dispute_key` whose `transactions` equal the branch set HQ chose from
  (copies written for a smaller set stay as they are, decision 006) to `status: "resolved"`, `resolution: { by: "hq",
  hlc, at: iso8601, chosen_txn, note }`, as the `hq` app user. For a fork `chosen_txn` must be one of `transactions`
  (400 otherwise); `unexpected_check_in` and `foreign_movement` close with `chosen_txn` null. `resolution.hlc` comes
  from HQ's clock and orders HQ's decisions; `at` is a label (decision 008). Returns the updated count.
- **HQ's clock:** `siab_hq` keeps one HLC for device `hq`, `hlc_now(clock, last, "hq")`, where `last` is the greater of
  the last it issued and the greatest `resolution.hlc` among the trip's exceptions it has read, so it is monotonic across
  restarts without a file.
- **Live, not settled** (decision 007, Phase 0): the conservation indicator reads `HOLDS · live` (or `N SKUs do not hold ·
  live`) and the panel header says `trip open: live view, nothing settled`. Closes and settlement are Phase 2.
- `POST /api/stage/hq-sale` body `{ "trip", "unit_id", "price"?: Money }` → writes one `transaction` as device
  `hq`: `kind: "sale"`, `from_custodian: "store-richmond"`, `to_custodian: "customer"`, `prev_txn: null`,
  `box: null`, `tender: { kind: "card_simulated", ... }`. This is the staged oversell: the flagship's count-based
  system sold a unit the box has. Returns the transaction id. The screen only offers units the ledger currently
  shows as held by the box or a tablet.
- `GET /api/box` → proxies `SIAB_BOX_STATUS_URL` when set, else `{ "configured": false }`.
- `GET /api/reconcile/status` → `{ "last_run": iso8601, "exceptions_written": n, "forks_open": n }`.

**Reconciler** (`siab_hq.reconcile`): every `SIAB_RECONCILE_INTERVAL_S` (injected clock; tests use virtual time)
load the trip's transactions and exceptions, `state = reduce(...)`, `docs = exceptions_for(state, "hq", trip, None)`,
upsert only the documents whose id does not exist, cache `state` for the API. Writes are idempotent by id. The
reconciler also runs once at startup and on `POST /api/reconcile/run`.

**CLI**: `python -m siab_hq serve [--trip ID] [--port N]`; `python -m siab_hq reconcile --once [--trip ID]` (prints
what it would write with `--dry-run`).

## Contract changes
- CC9 (#80, contracts 0.5.0, decisions 007 and 008): resolutions ordered by `resolution.hlc`; the reducer-driven queue;
  `foreign_movement`; the resolve endpoint binds to a branch set.

- CC3 (#4): the `exception` `resolution` block and the `hq` detector are in the schema; `transaction.box` nullable
  for `hq` writers.
- CC5 (#29, contracts 0.2.0): the conservation row gains `untraced` and `holds` can be false (`overpacked`,
  `untraced-unit`). Owned by WS1's interface; this workstream only displays it. No new change of its own.

## Exit criteria
- [ ] `test_queue_follows_reducer_not_documents` (#77 finding F: an open `hq` document whose fork no longer exists is
      listed as superseded) and `test_withdrawn_choice_is_back_on_queue` (fixture `latest-resolution-chooses-nothing`).
- [ ] `test_resolve_updates_only_the_matching_branch_set` and `test_resolve_rejects_a_choice_outside_the_branches`.

- [ ] `pytest tests/hq` passes against `FakeCapella` loaded from `contracts/fixtures/ledger/`; includes
      `test_reconciler_writes_one_exception_per_open_fork` (the `oversell-hq` and `double-scan` fixtures),
      `test_reconciler_is_idempotent_across_runs` (virtual time, three ticks, no duplicate writes),
      `test_resolve_updates_every_detectors_copy`, `test_conservation_rows_equal_fixture_expected`
      (`conservation-day`), `test_conservation_reports_why_a_row_fails` (`FakeCapella` loaded from `overpacked`:
      the response has `holds: false`, the `HAT-BRIM-OS` row has `store_on_hand: -1`, and the rendered screen
      carries `overdrawn by 1`; loaded from `untraced-unit`: the `SOC-WOOL-M` row has `untraced: 1` and the screen
      carries `1 untraced`), `test_stage_hq_sale_writes_root_sale_and_reconciler_forks_it`,
      `test_tree_matches_allocation_counts`.
- [ ] `python -m siab_hq reconcile --once --dry-run` against `FakeCapella` (an env flag selects it) prints the
      planned exception ids for the `oversell-hq` fixture and exits 0.
- [ ] `[capella]` After WS2's live seed: `python -m siab_hq serve` and `curl localhost:8788/api/conservation?trip=$SIAB_TRIP`
      returns `holds: true` with every row's `store_on_hand == opening_on_hand` (nothing packed yet). Recorded in the PR.
- [ ] `ruff check src/siab_hq tests/hq` prints no errors.
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

## Owner decisions
**Answered 2026-10-07** (closing comments on #6–#11): D1 yes (all Apple devices, free Apple account, repo public, macOS CI on every PR; decision 002); D2 yes, and featured in the demo (decision 001, WS8); D3 yes; D4: the box is a macOS laptop, the Pi on Debian Trixie is best-effort (decision 002); D5 yes; D6 yes, with the event renamed Richmond Riverfest (`trip-2026-10-18-riverfest`). Money is integer cents (decision 003). The lines below are the questions as asked; anything still open is marked.


- D6 (#11): names and prices shown on the HQ screen come from the seed; also whether the HQ screen shows the
  byte counter (recommend: yes, when reachable; blocks dispatch: no).
- D1 (#6): stack. Answered: yes.

## Verification plan

- Conservation holding live during a split, with tablet B out of range: WS7's rehearsal with the owner at the
  devices; the HQ screen is the instrument. Owner-present.
- The staged oversell producing exactly one dispute (several detectors, one `dispute_key`) on the live cluster:
  milestone audit, with `box` and `capella`.
- How the screen reads on a projector (type size, the "holds" indicator visible from the back of a room): owner,
  eyes. Filed as `needs-verification`.

## Tasks

Milestones and acceptance tests (ws-design):
1. `[any]` Reconciler over `CapellaGateway` and `siab_ledger`; `reconcile --once`. Accept: reconciler tests.
2. `[any]` API and screen; resolve; stage control; box panel; `ports/hq.md`. Accept: remaining `pytest tests/hq`.
3. `[capella]` Live run against the seeded cluster. Accept: the `[capella]` criterion.
4. `[any]` **PR.** One PR, `Closes #<issue>`; `needs-verification` issues filed and linked from "Not verified".
   Expected size: about 800 lines of code (tests and fixtures not counted; split the issue if it is over about
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
