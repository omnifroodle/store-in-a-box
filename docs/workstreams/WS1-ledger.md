# WS1: Custody ledger, reference implementation

**Milestone:** M1  **Depends on:** contracts v0.3.0 (CC1, CC3, CC5, CC6)  **Label:** `ws:1-ledger`  **Agent type:** ws-design
**Issue:** #12

The blueprint. The architect (`ws-architect`) writes it before any code is dispatched; the PR is judged against it.

## Scope

The custody ledger is the one piece of logic that every node runs: tablets, the HQ screen and the Capella-side
reconciler all take the same set of immutable `transaction` documents and must compute the same answer. This
workstream builds the **reference implementation in Python** and proves it against the golden fixtures in
`contracts/fixtures/ledger/`. WS4 ports the same rules to Swift and must pass the same fixtures; WS5 runs this
package in Capella.

Why a ledger and not a conflict resolver (owner decision D2, `for-foreman`): Couchbase Edge Server 1.1 has no
application hook for conflict resolution, and Capella App Services resolves conflicts from client pushes on the
client, not in the cloud. So Phase 0 makes the data **conflict-free by construction**: every custody movement is an
immutable `transaction` written once by one device and never edited; counts are derived, never stored and edited;
and the thing the spec calls "the resolver" is a deterministic reducer that turns a fork in a unit's custody chain
into an `exception` document with both transactions attached. Same outcome the spec asks for, with no document
ever having two writers.

Built here:
- `siab_ledger`: pure functions, no I/O, no Couchbase SDK. Build the per-unit custody chain from transactions,
  detect forks, derive the canonical holder of every unit, counts per custodian and per allocation, the Phase 0
  conservation rows, and the `exception` documents a detector must write.
- The hybrid logical clock (HLC) helpers: generate, parse, compare, merge on receive.
- A fixture runner: `python -m siab_ledger check` runs every fixture in `contracts/fixtures/ledger/` and, for
  fixtures marked `order_independent: true`, re-runs each with the transactions shuffled (seeded) and asserts the
  output is identical.
- `ports/ledger.md`: the reducer interface in language-neutral terms, which WS4 implements in Swift.

Left for later: allowances (Phase 1), two-level splits (the reducer handles any depth; the fixtures for a
three-deep tree arrive with Phase 1), case-level units, clock-skew staging (Phase 1 showcase 11; this includes a
blind movement whose writer's clock is behind the packer's, which finds no predecessor and stays a dangling root
until its writer moves the unit again, and two blind takes of a unit nobody packed, which never fork: CC6, #33),
any I/O.

## Files

Owned by this workstream:
- `src/siab_ledger/` (new: the package; `__init__.py`, `__main__.py`, `chain.py`, `hlc.py`, `exceptions.py`,
  `conservation.py`, `fixtures.py` or a layout of the implementer's choosing)
- `ports/ledger.md` (new: the reducer interface, see Interfaces)
- `ports/README.md` (new: one paragraph on what `ports/` holds; later workstreams append a line each)

Named edits in neighbours' code:
- `pyproject.toml`: already declares `siab_ledger` and the `siab-ledger` script (M0 setup PR). Edit it only to add a
  dependency it lacks.

## Interfaces

Document shapes are the foreman's: `contracts/schemas/store/transaction.schema.json`,
`allocation.schema.json`, `exception.schema.json` (CC3). This section fixes the *functions* over them.

**Vocabulary** (from CC3): a *unit* is one physical item, identified by its QR payload `<SKU>#<serial>`. A
*custodian* is `store-richmond`, `box-07`, `tablet-a`, `tablet-b`, `phone-1`, or the pseudo-custodian `customer`.
A *movement* is a `transaction` of kind `check_out`, `check_in` or `sale`, carrying `unit_id`, `from_custodian`,
`to_custodian`, `prev_txn` (the id of the movement that gave the writer custody; `null` when the unit leaves the
store root, or when the writer had no record of the unit: a *blind* movement, rule 1) and an `hlc`. A *fork* is
two or more movements with the same `(unit_id, predecessor)` (rule 2).

**`ports/ledger.md` fixes these operations**, which every implementation (Python here, Swift in WS4) provides:

```
reduce(transactions, resolutions) -> LedgerState
  transactions: every transaction document this node knows (any order, duplicates allowed by id)
  resolutions:  exception documents with status == "resolved" (their chosen_txn settles a fork)

LedgerState
  units[unit_id] -> { sku, holder: custodian | "customer" | null, allocation: id | null,
                      state: "held" | "sold" | "disputed", last_txn: id }
  counts[(custodian, sku)] -> int             (units in state "held" with that holder)
  allocation_counts[allocation_id] -> int     (units in state "held" inside that allocation)
  forks -> [ Fork{ unit_id, sku, prev_txn: id | null, branches: [txn ids sorted], resolved_by: id | null } ]

exceptions_for(state, detector, trip, box) -> [ exception documents ]
  one per unresolved fork and one per unexpected check-in (rule 6), id "exc::<detector>::<unit_id>::<hash8>"
  where hash8 is the first 8 hex chars of sha256 of the attached transaction ids joined by "|" after sorting;
  for a fork dispute_key is "<unit_id>|<prev_txn or 'root'>" and kind is "oversell" when the branch with the
  greatest hlc is a sale, else "double_scan"; for an unexpected check-in dispute_key is "<unit_id>|<check_in id>"
  and kind is "unexpected_check_in". Idempotent: same inputs, byte-identical output.

conservation(state, store, inventory) -> [ Row{ sku, opening_on_hand, received, left_store, untraced,
                                                 returned_to_store, store_on_hand, in_custody: {custodian: int},
                                                 sold, disputed, holds } ]
  untraced   = units of the SKU in the ledger whose every root is a check_in with prev_txn null
               (entered only by an unexpected check-in, rule 6; nothing says the store released it)
  left_store = every other unit of the SKU in the ledger (the release is presumed for any other root: a
               store root, or a dangling root, a blind movement with no predecessor in the input included)
  returned_to_store = of the left_store units, those held by the store
  Identity, true by construction and NOT the check:
    left_store + untraced == returned_to_store + sum(in_custody) + sold + disputed
  store_on_hand = opening_on_hand + received - left_store + returned_to_store   (may be negative)
  holds = untraced == 0 and store_on_hand >= 0
  Venue-side callers (no inventory) pass inventory = None and get rows whose opening_on_hand, received and
  store_on_hand are null; holds then means untraced == 0.
  (A sum over the unit states is an identity in a unit ledger; what holds checks is that the ledger agrees with
  what the store released: no unit the store never let go of, and no more units than it had. CC5, #29, after
  #27; see `contracts/fixtures/README.md`, which also fixes the order of every output list. Fixtures `overpacked`
  and `untraced-unit` are the ones where holds is false.)

HLC: string "<unix_ms:13 digits>-<counter:4 hex>-<device_id>", compared lexicographically.
  hlc_now(clock, last) -> hlc        (clock is injected; tests use a fake clock)
  hlc_receive(local_last, remote, clock) -> hlc
```

**Reducer rules** (also written into `ports/ledger.md`, and they are what the fixtures test):
1. Movements for a unit form a forest by *predecessor* (edge from the predecessor to the movement). A movement's
   predecessor is the transaction its `prev_txn` names, except for a *blind* movement: a `check_out` or `sale`
   with `prev_txn == null` whose `from_custodian` is not the store (its writer had no record of the unit, for
   example a tablet taking a unit off the box before the pack replicated; CC6, #33). A blind movement's
   predecessor is the movement of the same unit with `to_custodian == its from_custodian` and the greatest `hlc`
   below its own, among every movement of the unit in the input (branches a resolution set aside included); when
   there is none it has no predecessor. A *root* is a movement with no predecessor: a *store root* (`prev_txn`
   null, `from_custodian` the store), a *dangling* root (`prev_txn` names a transaction this node does not have,
   or a blind movement whose implied predecessor has not arrived; not an error), or a `check_in` with `prev_txn`
   null (rule 6). Successor, descendant and leaf follow this relation, not `prev_txn` alone. The `hlc` bound is
   what keeps the forest acyclic (a later return to the box also gave the box custody; fixture
   `null-root-take-returned`).
2. A *fork* is a group of two or more movements with the same `(unit_id, predecessor)`. A *root fork* is two or
   more store roots of one unit (two packs, or a pack and HQ's sale). Dangling roots are never a fork, whether
   their missing predecessors are named or implied, and a `check_in` with `prev_txn == null` never joins any fork
   (rule 6 covers it). So a take written before the pack replicated is the pack's child once the pack arrives
   (fixture `null-root-take-pack-arrives`), and a double take with one blind side forks at the pack
   (`null-root-double-take`).
3. An unresolved fork makes the unit `disputed`: holder `null`, counted under `disputed`, not under any custodian
   or allocation. Only HQ resolves: a resolution counts only when `resolution.by == "hq"` and any other is ignored
   (peer-to-peer sync never runs the App Services sync function, so the reducer enforces it; fixture
   `non-hq-resolution-ignored`). A resolution naming `chosen_txn` makes that branch canonical; the other branches and their
   descendants are ignored for holder and counts.
4. Otherwise the unit's *leaf* is the movement with no successor; when several chains exist (dangling roots), the
   leaf with the greatest `hlc` wins. Holder is `leaf.to_custodian`, allocation `leaf.to_allocation`, state `sold`
   when `leaf.kind == "sale"` else `held`.
5. Reduction is a pure function of the set of transactions and resolutions: duplicates by id collapse, order of
   arrival never changes the result (the `order_independent` fixtures prove it).
6. A `check_in` whose `from_custodian` is neither its `device` nor its `box` (the box never writes; tablets write
   on its behalf), or whose `prev_txn` is `null` (the writer had no record of the unit; `from_custodian` is then
   `"unknown"`), is an *unexpected check-in*: the movement stands (the
   physical scan is the stronger evidence, the unit is now held by `to_custodian`) and an exception of kind
   `unexpected_check_in` attaches the check-in and, when present, its predecessor.
7. `exceptions_for` never updates an existing exception: a new branch at the same fork yields a new document id
   (different hash). Resolutions are HQ's to write (WS5); detectors only create, and `exceptions_for` leaves out any exception whose
   `dispute_key` and `transactions` match a resolution in its input. `proposed_resolution.note` is fixed text per
   kind, given in `contracts/fixtures/README.md`.

CLI (fixed): `python -m siab_ledger check [--fixtures DIR] [--seed N]` exits 0 and prints one line per fixture
(`PASS <name>` / `FAIL <name>: <first difference>`), exits 1 on any failure.

## Contract changes

- CC1 (#2): `contracts/` layout, schema conventions, `contracts/VERSION`, `scripts/check_contracts.py`.
- CC3 (#4): `store.allocation`, `store.transaction`, `store.exception` schemas, the id and HLC conventions, and
  the ledger golden fixtures under `contracts/fixtures/ledger/` (scenario list in the issue).
- CC5 (#29, contracts 0.2.0): conservation `holds` is a check, not an identity (#27). The row gains `untraced`;
  `holds` is `untraced == 0` at the venue and also `store_on_hand >= 0` with inventory; fixtures `overpacked`
  and `untraced-unit` are the first with `holds: false`.
- CC6 (#33, contracts 0.3.0): a blind movement (`prev_txn` null from a custodian other than the store) continues
  the movement that gave that custodian custody instead of forming a root fork with the pack (#32); rules 1 and
  2 above. Fixtures `null-root-take-pack-arrives`, `null-root-double-take`, `null-root-take-returned`.
All four are applied before dispatch.

## Exit criteria

- [ ] `python -m siab_ledger check` passes every fixture in `contracts/fixtures/ledger/`, including the shuffled
      re-runs of the `order_independent` ones.
- [ ] `pytest tests/ledger` passes; it includes `test_fork_detection_is_order_independent` (property-style: random
      permutations of each fixture's transactions give identical `LedgerState`), `test_dangling_predecessor_is_not_a_fork`,
      `test_exception_id_is_deterministic`, `test_hlc_monotonic_under_fake_clock`,
      `test_resolution_settles_fork`, and `test_conservation_holds_can_fail` (the `overpacked` fixture gives
      `holds: false` only with inventory, with `store_on_hand == -1`; `untraced-unit` gives `holds: false` in both
      modes with `untraced == 1`; a build of `conservation` that returns `holds: true` unconditionally fails it),
      and `test_blind_take_links_under_the_pack` (`null-root-take-pack-arrives` gives no fork and `tablet-b` as
      holder; `null-root-double-take` gives one fork whose `prev_txn` is the pack; `null-root-take-returned`
      terminates with the chain pack, take, return, take; a build that puts every null-`prev_txn` movement into a
      root fork fails the first, and one that links a blind movement to the latest movement into its source
      custodian, with no `hlc` bound, fails or hangs on the third).
- [ ] `python scripts/check_contracts.py` passes (every exception document `exceptions_for` emits for the fixtures
      validates against `contracts/schemas/store/exception.schema.json`; the test writes them to a temp dir and runs
      the validator on it, or calls the validator's function).
- [ ] `ports/ledger.md` exists and names every operation and rule in the Interfaces section above.
- [ ] `ruff check src/siab_ledger tests/ledger` prints no errors.
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

## Owner decisions
**Answered 2026-10-07** (closing comments on #6–#11): D1 yes (all Apple devices, free Apple account, repo public, macOS CI on every PR; decision 002); D2 yes, and featured in the demo (decision 001, WS8); D3 yes; D4: the box is a macOS laptop, the Pi on Debian Trixie is best-effort (decision 002); D5 yes; D6 yes, with the event renamed Richmond Riverfest (`trip-2026-10-18-riverfest`). Money is integer cents (decision 003). The lines below are the questions as asked; anything still open is marked.


- D2 (#7): ledger-and-reducer instead of a replication-layer conflict resolver: answered yes (decision 001); the owner
  wants the pattern featured (WS8).
- D3 (#8): unit-level QR, payload `<SKU>#<serial>`: answered yes (5 labels per SKU).

## Verification plan

Nothing here needs a device or a live service; the fixtures are the verification. What the fixtures cannot show is
whether the Swift port (WS4) and this package agree on inputs the fixtures do not cover; the milestone audit runs
`python -m siab_ledger check` and WS4's `swift test` fixture suite against the same `contracts/fixtures/ledger/`
directory and compares the two reports line by line.

## Tasks

Milestones and acceptance tests (ws-design):
1. `[any]` HLC and chain building: `reduce` over linear chains (pack, sell, split, merge). Accept: fixtures
   `pack-and-sell`, `split-and-merge`, `merge-order-independent` pass.
2. `[any]` Forks, dangling branches, blind movements, resolutions, `exceptions_for`. Accept: fixtures `double-scan`,
   `oversell-hq`, `unexpected-check-in`, `dangling-predecessor`, `resolved-fork`, `null-root-take`,
   `null-root-take-pack-arrives`, `null-root-double-take`, `null-root-take-returned` pass; exception documents
   validate.
3. `[any]` `conservation` rows, venue-side and HQ-side. Accept: fixtures `conservation-day` (every row holds),
   `overpacked` (holds only venue-side) and `untraced-unit` (holds in neither mode) pass in both modes.
4. `[any]` `ports/ledger.md`, `ports/README.md`, the CLI, the `pyproject.toml` entries.
5. `[any]` **PR.** One PR, `Closes #<issue>`; `needs-verification` issues filed and linked from "Not verified"
   (expected: none). Expected size: about 700 lines of code (tests and fixtures not counted; split the issue if it is
   over about 1,500).

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
