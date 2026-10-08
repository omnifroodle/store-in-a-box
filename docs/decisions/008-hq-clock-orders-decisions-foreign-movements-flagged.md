# 008: HQ's clock orders its decisions; a movement by a device that did not act for it is flagged, never blocked

Status: accepted. Issues: #72, #77, #80 (CC9).

The gate on contracts 0.4.0 (#72) found two readings of rule 3 the fixtures did not pin and a resolution ordering
that rested on a wall-clock label; the owner asked who the boss of a dispute is, whether the system should check
that a device only moves what it controls, and for one ordering convention.

1. **The choice.** HQ is the boss of a dispute, and its latest word stands even when that word is "no choice": a
   withdrawn choice reopens the fork rather than reviving an older answer, and the dispute is back on the queue by
   the reducer's open fork, not by a document. Its decisions are ordered by its own hybrid logical clock
   (`resolution.hlc`), one writer with one clock, and `resolution.at` is a label. Movements a resolution set aside
   raise nothing, so HQ's answer is not undone by activity on a branch it closed. A movement whose writer acted
   for neither custodian it names on its own side (a `check_out` onto, or a `sale` from, a custodian that is not
   the writer, its box, or the store when the writer is HQ) is *foreign*: it stands, because a scan is never
   refused and the ledger follows it, and it raises a `foreign_movement` exception. Rejected: taking the latest
   resolution that names a branch (quietly revives an answer HQ withdrew); ordering by `resolution.at` with a
   format pattern (a label HQ's wall clock can set back); extending `unexpected_check_in` to cover foreign sales
   (its fixed note says "checked in", and HQ and the explainer want the two apart); checking a take by whom it
   takes from (the taker is the one who scans, and a phone taking from a tablet is the Phase 1 split).
2. **What it costs.** Every resolved document carries `hlc`, so WS5 keeps an HLC for `hq` (seeded from the
   greatest `resolution.hlc` it has read) and the Swift port adds rule 8 and the set-aside check. A remote tender
   or a pre-order is a flagged sale until it has a document kind of its own. The staged HQ sale is exempt by the
   rule itself (HQ acts for the store), so the Phase 0 oversell still raises exactly one exception.
3. **When to revisit.** Phase 1 (allowances join the ledger, pre-orders and remote tenders get their kinds), or when
   a second HQ writer appears (two processes resolving as `hq`: the `_id` tie-break stands but is arbitrary).

Contract change: version 0.5.0 (`resolution.hlc`, `kind: foreign_movement`, rules 3, 7, 8; six fixtures).
