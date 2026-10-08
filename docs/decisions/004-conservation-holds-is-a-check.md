# 004: Conservation `holds` checks the ledger against what the store released

Status: accepted. Issues: #27, #29.

The review gate on #22 found that `holds` in contracts 0.1.0 was an identity: `store_on_hand` was derived from the
same four unit states that `holds` summed, so every ledger balanced, including 14 units packed against an opening
on-hand of 12. Phase 0's acceptance is "the conservation query holding", which means nothing if it cannot fail.

1. **The choice.** A sum over unit states is an identity by design (a unit is in exactly one place), so the row
   states it as one and checks something else: that the ledger agrees with what the store released. A row fails
   when a unit is **untraced** (it entered by an unexpected check-in and no pack for it ever arrived; visible at the
   venue) or when the store is **overdrawn** (the ledger names more units than the store had; `store_on_hand < 0`,
   HQ only). Dangling roots count as released, so a unit mid-replication never turns a row red on stage. Rejected:
   checking that no unit is counted under two states, which only a broken reducer can violate and the fixtures
   already pin.
2. **What it costs.** The row gains a required field, `untraced`, so every implementation and the HQ screen change
   (contracts 0.2.0). A failing row writes no exception in Phase 0: the exception schema is per unit, and per-SKU
   gaps go to Eventing in Phase 2; the HQ screen shows the reason (`overdrawn by N`, `N untraced`).
3. **When to revisit.** Phase 2, when Eventing maintains on-hand and a failing row can raise its own exception.

Contract change: version 0.2.0 (`untraced` in the conservation row; fixtures `overpacked` and `untraced-unit`).
