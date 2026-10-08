# Port: the custody ledger reducer

Owner: WS1 (`src/siab_ledger/`, the Python reference implementation). Users: WS4 (the same operations in Swift, on
the tablets and phones), WS5 (the Capella-side reconciler and the HQ screen run the Python package). Every
implementation must pass the golden fixtures in `contracts/fixtures/ledger/`; the fixtures, not this page and not the
Python code, are the source of truth. Semantics come from `contracts/fixtures/README.md` (rules 1 to 7 and the output
order) and decision 001; this page restates them as an interface.

The operations are pure: no I/O, no clock reads (the clock is injected), no database. The caller reads the
`transaction` and `exception` documents (shaped by `contracts/schemas/store/`, each with its `_id`) and writes what
`exceptions_for` returns.

## Vocabulary

- *Unit*: one physical item, `unit_id` = its QR payload `<SKU>#<serial>`.
- *Custodian*: `store-richmond`, `box-07`, `tablet-a`, `tablet-b`, `phone-1` (registry:
  `contracts/fixtures/seed/custodians.json`), or the pseudo-custodians `customer` (where a sale goes) and `unknown`
  (where a check-in of a unit with no record comes from).
- *Movement*: a `transaction` (`check_out`, `check_in` or `sale`) of one unit from `from_custodian` to
  `to_custodian`, naming `prev_txn` (the movement that gave the writer custody, or null) and stamped with an `hlc`.
- *Blind movement*: a `check_out` or `sale` with `prev_txn` null whose `from_custodian` is not the store (the writer
  had no record of the unit).
- *Store root*: a movement other than a `check_in`, with `prev_txn` null and `from_custodian` the store.
- *Fork*: two or more movements with the same `(unit_id, predecessor)`.

## Operations

```
reduce(transactions, resolutions, store) -> LedgerState
  transactions: every transaction this node knows, any order, duplicates allowed by id
  resolutions:  exception documents; only those with status "resolved" and resolution.by "hq" count (rule 3)
  store:        the store custodian id ("store-richmond" in Phase 0), which tells a store root from a blind movement

LedgerState
  units[unit_id] -> Unit{ sku, holder: custodian | "customer" | null, allocation: alloc id | null,
                          state: "held" | "sold" | "disputed", last_txn: txn id | null }
  counts[(custodian, sku)] -> int           units in state "held" with that holder
  allocation_counts[allocation_id] -> int   units in state "held" in that allocation, for every allocation id named
                                            in any transaction's from_allocation or to_allocation (zeros included)
  forks -> [ Fork{ unit_id, sku, prev_txn: txn id | null, branches: [txn id, sorted], resolved_by: exc id | null } ]
  (and, for the next two operations: the transactions by id, the counting resolutions, each movement's predecessor,
   and the set of untraced units)

exceptions_for(state, detector, trip, box, detected_at = null) -> [ exception document ]
  sorted by _id; each carries its "_id"; "detected_at" (the detector's hlc) only when given

conservation(state, store, inventory) -> [ Row{ sku, opening_on_hand, received, left_store, untraced,
                                                 returned_to_store, store_on_hand, in_custody: {custodian: int},
                                                 sold, disputed, holds } ]
  inventory: the store's inventory documents (HQ side), or null at the venue

hlc_now(clock, last, device = device of last) -> hlc
hlc_receive(local_last, remote, clock, device = device of local_last) -> hlc
```

Python names: `siab_ledger.reduce(transactions, resolutions, *, store)`, `siab_ledger.exceptions_for(state, detector,
trip, box, *, detected_at=None)`, `siab_ledger.conservation(state, store, inventory)`, `siab_ledger.hlc_now`,
`siab_ledger.hlc_receive`, and `siab_ledger.exception_id(detector, unit_id, txn_ids)`. `LedgerState.to_json()` and
`Row.to_json()` give the fixtures' shapes.

## Reducer rules

1. **Predecessor.** A unit's movements form a forest by predecessor. A movement's predecessor is the transaction its
   `prev_txn` names, whether or not this node has it, except for a blind movement, whose predecessor is the movement
   of the same unit with `to_custodian` equal to the blind movement's `from_custodian` and the greatest `hlc` below
   its own, among every movement of the unit in the input (branches a resolution set aside included); when there is
   none it has no predecessor. The `hlc` bound keeps the forest acyclic. A *root* is a movement whose predecessor is
   not in the input: a store root, a *dangling root* (`prev_txn` names a transaction this node does not have, or a
   blind movement with no predecessor; not an error), or a `check_in` with `prev_txn` null. Successor, descendant
   and leaf follow this relation, not `prev_txn` alone.
2. **Fork.** Two or more movements with the same predecessor id, in the input or not (two dangling roots naming the
   same missing transaction are a fork, found before it arrives and unchanged by its arrival); its `prev_txn` is that
   id. Two or more store roots of one unit are a *root fork* (`prev_txn` null). A blind movement with no predecessor
   is in no fork, and a `check_in` with `prev_txn` null never joins any fork.
3. **Disputed; only HQ resolves.** An unresolved fork makes the unit `disputed`: `holder`, `allocation` and
   `last_txn` null, counted under `disputed` and under no custodian or allocation. A resolution counts only when its
   `status` is `resolved` and `resolution.by` is `hq`; any other is ignored everywhere. A resolution settles the fork
   of its `unit_id` whose branches include `resolution.chosen_txn`: that branch is canonical, the other branches and
   their descendants are ignored for holder and counts, and the fork stays in `forks` with `resolved_by` = the
   resolution's `_id`.
4. **Leaf.** Otherwise the unit's leaf is the canonical movement with no canonical successor; when several chains
   exist, the leaf with the greatest `hlc` wins. `holder` = `leaf.to_custodian`, `allocation` = `leaf.to_allocation`,
   `last_txn` = the leaf's id, `state` = `sold` when `leaf.kind` is `sale`, else `held`.
5. **Pure.** The result is a function of the set of transactions and the set of resolutions: duplicates by id
   collapse and arrival order never changes it.
6. **Unexpected check-in.** A `check_in` whose `from_custodian` is neither its `device` nor its `box`, or whose
   `prev_txn` is null, is unexpected. The movement stands (the physical scan is the stronger evidence) and an
   `unexpected_check_in` exception attaches the check-in and, when the input has it, its `prev_txn`.
7. **Detectors only create.** `exceptions_for` emits one document per unresolved fork and one per unexpected
   check-in, and leaves out any whose `dispute_key` and `transactions` match a resolution that counts. A new branch at
   the same fork gives a new document id (a different hash), never an update.

## Exception documents

- `_id` = `exc::<detector>::<unit_id>::<hash8>`, `hash8` = the first 8 hex characters of sha256 over the attached
  transaction ids, sorted and joined by `|`.
- Fork: `kind` = `oversell` when the branch with the greatest `hlc` is a `sale`, else `double_scan`; `fork_txn` =
  the fork's `prev_txn`; `dispute_key` = `<unit_id>|<prev_txn or "root">`; `transactions` = the branches.
- Unexpected check-in: `kind` = `unexpected_check_in`, `fork_txn` null, `dispute_key` = `<unit_id>|<check-in id>`.
- `transactions` sorted; `branches[i]` = `{txn, device, kind, to_custodian, hlc}` of `transactions[i]`.
- `proposed_resolution` is fixed per kind, byte for byte (`contracts/fixtures/README.md`): `oversell` gives
  `refund`, the others `review`, with the notes given there.
- `status` `open`, `resolution` null, `detected_by` the detector, `box` the box (null when the detector is `hq`).
- Same state in, byte-identical documents out (key order as in the fixtures).

## Conservation

- `untraced`: units of the SKU whose every root is a `check_in` with `prev_txn` null (nothing says the store
  released them). `left_store`: every other unit of the SKU in the ledger (release is presumed for a store root or a
  dangling root). `returned_to_store`: the `left_store` units held by the store. `in_custody`: held units per holder
  other than the store, holders with at least one. `sold`, `disputed`: units in those states.
- With inventory: rows for the SKUs in the ledger or in the store's inventory; `opening_on_hand` and `received` from
  the inventory document (0 when the SKU has none), `store_on_hand = opening_on_hand + received - left_store +
  returned_to_store` (may be negative), `holds = untraced == 0 and store_on_hand >= 0`.
- Venue (inventory null): rows for the SKUs in the ledger; `opening_on_hand`, `received`, `store_on_hand` null;
  `holds = untraced == 0`.
- Not a check, true by construction: `left_store + untraced == returned_to_store + sum(in_custody) + sold +
  disputed`.

## Output order

`units` keyed by `unit_id`; `counts` rows with `qty >= 1` sorted by custodian then sku; `allocation_counts` keyed by
id; `forks` sorted by `unit_id` then `prev_txn` (null first) with `branches` sorted; exception documents sorted by
`_id`; conservation rows sorted by sku, `in_custody` keyed by custodian.

## HLC

`<unix_ms:13 digits>-<counter:4 lowercase hex>-<device_id>`, compared lexicographically (which is causal order).
`clock` returns unix milliseconds and is injected (tests use a fake clock).

- `hlc_now`: the clock's time with counter 0 when the clock is ahead of `last`, else `last`'s time with the counter
  plus one. Always strictly greater than `last`.
- `hlc_receive`: the greatest of the local time, the remote time and the clock; the counter is one more than the
  largest counter among those carrying that time, or 0 when only the clock does. Always strictly greater than both
  `local_last` and `remote`; the device is always the local one.
- A counter at `ffff` carries into the milliseconds (time + 1, counter 0) rather than blocking a scan.

## Fixture runner

`python -m siab_ledger check [--fixtures DIR] [--seed N]` (also `siab-ledger check`) runs every fixture in
`contracts/fixtures/ledger/` (or `DIR`): `reduce`, then `exceptions_for` with `expected.exceptions.detector`, then
`conservation` with the inventory (when not null) and without. A fixture with `order_independent: true` is re-run
reversed and with its transactions and resolutions shuffled (seeded by `N`, default 0; every other run also delivers
some documents twice). One line per fixture, `PASS <name>` or `FAIL <name>: <first difference>`, in file-name order;
exit 1 on any failure.
