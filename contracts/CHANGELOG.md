# Contracts changelog

One line per version, newest first: version, date, what was added (additive) or changed (breaking). The first
version line must match `VERSION` (`scripts/check_contracts.py` checks it).

- 0.2.0 (2026-10-08): conservation `holds` is a check, not an identity (#27, CC5 #29): the row gains `untraced`;
  `holds` is `untraced == 0` at the venue and also `store_on_hand >= 0` with inventory; fixtures `overpacked` and
  `untraced-unit` are the first with `holds: false`. A new required field, so a minor bump (decision 004).
- 0.1.0 (2026-10-07): first contracts. Layout, conventions and validator (CC1 #2); `store.product`, `store.inventory`,
  `store.trip` and the Phase 0 seed (CC2 #3); `store.allocation`, `store.transaction`, `store.exception` and eleven
  ledger scenarios (CC3 #4, decision 001); the custodian registry, channel names and the sync-function cases (CC4 #5).
  Only HQ resolves an exception, in the sync function and in the reducer.
  Money is integer cents (decision 003).
