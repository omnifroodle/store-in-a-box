# 005: A blind movement continues the chain its writer had no record of

Status: accepted. Issues: #32, #33 (CC6).

A tablet that scans a unit off the box before the pack of that unit has replicated writes the take with
`prev_txn: null`, because it has no record to name. Contracts 0.2.0 made that take a root beside the pack, and
rule 2 made a root fork of the two once the pack arrived: a `double_scan` for what was only replication order.

1. **The choice.** The reducer, not the writer, closes the gap. A *blind movement* (`prev_txn` null,
   `from_custodian` not the store, not a check-in) still names where the unit came from, and the reducer links it
   under the movement that gave that custodian custody: the one with `to_custodian` equal to its `from_custodian`
   and the greatest `hlc` below its own. With the pack in the input the take is the pack's child; without it the
   take is a dangling root, as before. A genuine double take forks at the pack, one branch by `prev_txn` and one
   implied. Rejected: making the writer wait or refuse (it blocks a scan on replication, which the design promises
   never to do); treating a blind movement as a plain dangling root (no false fork, but a double take where one
   tablet had the record goes uncaught).
2. **What it costs.** One more clause in rules 1 and 2 for both reducers (Python and Swift), and the `hlc` bound,
   which exists so the link can never cycle (a return to the box after the take also gave the box custody). A
   blind take written by a device whose clock is behind the packer's finds no predecessor and loses the leaf race
   until its writer moves the unit again; Phase 1's clock-skew staging revisits this.
3. **When to revisit.** Phase 1 (clock skew, allowances), or if the writers gain a way to name a pack they have
   not seen.

Contract change: version 0.3.0 (rules 1 and 2; fixtures `null-root-take-pack-arrives`, `null-root-double-take`,
`null-root-take-returned`).
