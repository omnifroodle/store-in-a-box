# 006: A resolution binds to the branches it was written for

Status: accepted. Issues: #58, #70 (CC8).

Building the reference reducer (#60) found five cases the fixtures did not pin and the rules read two ways: a
third branch at a resolved fork, an untraced unit held by the store, a fork inside a branch HQ set aside, two HQ
resolutions of one fork, and a resolution that chooses nothing.

1. **The choice.** A resolution matches a fork by `dispute_key` and `transactions` (the same test rule 7 already
   used to suppress an exception) and settles it only when `chosen_txn` is one of those branches. So a new branch
   at a settled fork reopens it (the unit is `disputed` and the detector writes a new document; HQ never loses a
   scan), a fork among set-aside movements is not reported (HQ's answer stands), the latest `resolution.at` wins
   among several, and `chosen_txn` null settles nothing but still closes the exception. `returned_to_store`
   counts every unit the store holds so the conservation row partitions the units. Rejected: letting a resolution
   settle any fork whose branches include its `chosen_txn` (a third scan is set aside silently); reporting forks
   inside set-aside branches (undoes HQ's resolution for a fork that cannot change the holder); picking among
   resolutions by `_id` (picks by detector name, not by HQ's latest decision).
2. **What it costs.** HQ must resolve again when a late branch arrives at a fork it already settled, and the
   HQ screen (WS5) must require a `chosen_txn` when resolving a fork. HQ writes `resolution.at` in UTC with a `Z`
   suffix and whole seconds so both reducers can compare it as a string.
3. **When to revisit.** Phase 1 (allowances join the ledger), or if HQ gains a way to resolve a dispute key once
   for every copy and every future branch.

Contract change: version 0.4.0 (rules 2, 3 and 7, `returned_to_store`; six fixtures).
