# 001: Custody is a conflict-free ledger, not data guarded by a replication-layer conflict resolver

Status: accepted. Issue: #7.

`docs/SPEC.md` section 4.4 assumed a custom conflict resolver running "on the box and in App Services". Checked on
2026-10-07: Couchbase Edge Server 1.1 has no application hook for conflict resolution, and Capella App Services
rejects a conflicting client push and leaves the resolution to Couchbase Lite on the client. A resolver that runs on
only some nodes would make "the same result whichever order the pieces meet in" depend on where a conflict happens to
be noticed.

1. **The choice.** Custody data is conflict-free by construction. Every movement (pack, take, return, sell) is an
   immutable `transaction`, written once by one device. Counts are derived from the transactions, never stored and
   edited. Each movement names its predecessor (`prev_txn`); two movements with the same predecessor are a fork (the
   double-scan, the oversell). One deterministic reducer, the same rules in Python (WS1) and Swift (WS4) and checked by
   the golden fixtures in `contracts/fixtures/ledger/`, runs on every tablet and in Capella and turns each fork into an
   `exception` with both transactions attached; the unit stays `disputed` until HQ chooses a branch. Rejected: a
   resolver callback on the replication layer, which neither Edge Server nor App Services offers for this topology.
   Couchbase Lite's `ConflictResolver` is still registered for the rare same-document case (an allocation closed
   twice).
2. **What it costs.** Counts are queries, so the Shelf screen needs a derived local view. Several detectors may write
   their own copy of one dispute, so HQ groups exceptions by `dispute_key`. Two implementations of the reducer must be
   kept in step, which is why the fixtures, not either language, are the source of truth.
3. **When to revisit.** If Edge Server or App Services gains an application conflict-resolution hook for this
   topology, or at Phase 1 when allowances join the ledger.

The owner asked for more than approval: this pattern is a headline feature of the design and is to be documented
and called out at a high level in the demo (WS8). Demo talking point 7 becomes "conflict-free by construction".

Contract change: version 0.1.0 (the `transaction`, `allocation` and `exception` schemas and the ledger fixtures, CC3 #4).
