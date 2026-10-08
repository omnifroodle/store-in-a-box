# Contracts changelog

One line per version, newest first: version, date, what was added (additive) or changed (breaking). The first
version line must match `VERSION` (`scripts/check_contracts.py` checks it).

- 0.1.0 (2026-10-07): first contracts. Layout, conventions and validator (CC1 #2); `store.product`, `store.inventory`,
  `store.trip` and the Phase 0 seed (CC2 #3); `store.allocation`, `store.transaction`, `store.exception` and ten
  ledger scenarios (CC3 #4, decision 001); the custodian registry, channel names and the sync-function cases (CC4 #5).
  Money is integer cents (decision 003).
