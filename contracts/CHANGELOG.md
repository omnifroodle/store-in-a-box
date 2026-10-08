# Contracts changelog

One line per version, newest first: version, date, what was added (additive) or changed (breaking). The first
version line must match `VERSION` (`scripts/check_contracts.py` checks it).

- 0.6.0 (2026-10-08): HQ's closure of an `unexpected_check_in` or a `foreign_movement` holds by `kind` and
  `dispute_key` (the movement), whatever its `transactions`, so a predecessor that arrives after the close no longer
  reopens it (rule 7; #83, CC10 #86, decision 009); rule 8 names who acts for the store (only `hq`) and that `hq`
  has no box. Fixtures `closed-foreign-movement-predecessor-arrives`,
  `closed-unexpected-check-in-predecessor-arrives`, `closed-foreign-movement-fork-at-same-key`, `foreign-store-sale`,
  `foreign-check-out-to-store`, `foreign-hq-check-out`. A changed rule, so a minor bump.
- 0.5.0 (2026-10-08): HQ's own clock orders its decisions: `resolution.hlc` (new, required) is what rule 3 compares
  and `resolution.at` is a label; the latest matching resolution decides even when it chooses nothing, and an
  earlier choice is not revived; set-aside movements raise no `unexpected_check_in`; rule 8, a *foreign* movement
  (a `check_out` onto, or a `sale` from, a custodian its writer does not act for) stands and gets a
  `foreign_movement` exception, a new kind, never a refused scan (#72, #77, CC9 #80, decision 008). Fixtures
  `latest-resolution-chooses-nothing`, `unexpected-check-in-inside-set-aside-branch`, `resolution-order-by-hlc`,
  `foreign-sale`, `foreign-check-out`, `second-level-take`; `resolution.hlc` added to every resolved fixture. A new
  required field, a new enum value and changed rules, so a minor bump.
- 0.4.0 (2026-10-08): a resolution binds to the branches it was written for (rule 3: it matches a fork by
  `dispute_key` and `transactions`; a third branch reopens the fork; forks among set-aside movements are not
  reported; the latest `resolution.at` wins among several; `chosen_txn` null settles nothing), and
  `returned_to_store` counts every unit the store holds, untraced included (#58, CC8 #70, decision 006). `reduce`
  takes the store (#59); rule 2 wording and the versioning rule for rule changes (#56). Fixtures
  `third-branch-at-resolved-fork`, `untraced-unit-returned`, `fork-inside-set-aside-branch`,
  `two-resolutions-one-fork`, `resolution-without-choice` and `null-root-double-take-no-pack` (the #56 gap).
  Changed rules, so a minor bump.
- 0.3.1 (2026-10-08): rule 2 restored for named predecessors: two dangling roots whose `prev_txn` name the same
  missing transaction are a fork, as in 0.2.0 (0.3.0's wording had dropped it, unrecorded; #37, CC7 #44); a blind
  movement with no predecessor is still in no fork. Fixtures `dangling-double-take` (pins it),
  `null-root-take-after-return` (the greatest `hlc` below the blind movement), `null-root-sale-oversell` (a blind
  sale) and `null-root-take-resolved-fork` (a set-aside branch as the implied predecessor), the gaps in #36. A
  wording correction and fixtures, so a patch bump.
- 0.3.0 (2026-10-08): a blind movement (prev_txn null from a custodian other than the store: the writer had no
  record of the unit) continues the movement that gave its from_custodian custody instead of forming a root fork
  with the pack (#32, CC6 #33, decision 005); rules 1 and 2. Fixtures `null-root-take-pack-arrives`,
  `null-root-double-take` and `null-root-take-returned`. A changed rule, so a minor bump.
- 0.2.0 (2026-10-08): conservation `holds` is a check, not an identity (#27, CC5 #29): the row gains `untraced`;
  `holds` is `untraced == 0` at the venue and also `store_on_hand >= 0` with inventory; fixtures `overpacked` and
  `untraced-unit` are the first with `holds: false`. A new required field, so a minor bump (decision 004).
- 0.1.0 (2026-10-07): first contracts. Layout, conventions and validator (CC1 #2); `store.product`, `store.inventory`,
  `store.trip` and the Phase 0 seed (CC2 #3); `store.allocation`, `store.transaction`, `store.exception` and eleven
  ledger scenarios (CC3 #4, decision 001); the custodian registry, channel names and the sync-function cases (CC4 #5).
  Only HQ resolves an exception, in the sync function and in the reducer.
  Money is integer cents (decision 003).
