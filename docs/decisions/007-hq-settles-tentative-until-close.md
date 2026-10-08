# 007: HQ settles; every node's view is tentative until the trip close, and a close is a manifest

Status: proposed. Issues: #72, #77, #81, #80 (CC9).

The reducer presumes on a partial view (a dangling root is counted as released, a blind movement links to the
latest predecessor it can see), and the owner asked who the authority is and how a tentative fact is told from a
settled one. The foreman proposed HQ as the authority, closes, and a per-device sequence to make a device's tail
visible.

1. **The choice.** HQ (Capella) is the authority for disputes, inventory and, from Phase 1, money and allowances.
   Every node's reduced state is tentative, HQ's included, until HQ writes a trip close. A device close is one
   immutable document per writer per trip that lists the ids of every transaction the writer wrote (its manifest)
   and its own sales totals; HQ compares each manifest with what it holds (complete, pending, inconsistent) and,
   when every device in the trip is closed and no dispute is open, writes the trip close with the settled
   conservation rows. Movements and resolutions after a close are adjusting entries that HQ re-settles with a new
   trip close; nothing is edited. The transaction document is unchanged: no per-device sequence (a manifest is
   exact at close time and has none of a counter's epoch problems, #77) and no version vector (a vector says what
   a writer saw; settlement needs what it wrote). Closes arrive in Phase 2; Phase 0 labels HQ's view "live",
   drives HQ's queue from the reducer rather than from documents, and shows each tablet its unpushed tail.
   Rejected: a sequence on every movement (#77); a box close (the box never writes; its custody ends when its
   allocations close); settling on the tablets (they never see the inventory and never see every writer).
2. **What it costs.** A trip is never "done" until someone closes every device and HQ closes the trip, and a
   device that dies unclosed needs an owner's override (closed over, recorded). A wiped device's unpushed tail is
   lost and no close reveals it; the Diagnostics line is the only witness. Phase 2 adds a collection, a port
   function and about 650 lines across six workstreams.
3. **When to revisit.** Phase 1 (allowances: a settled balance is money), or if Phase 2's explainer needs a
   per-movement completeness signal the manifest does not give.

Contract change: none now (0.5.0 is CC9's); the `close` schema and `settlement` fixtures at M3 planning.
