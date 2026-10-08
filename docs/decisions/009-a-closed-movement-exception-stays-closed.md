# 009: HQ's closure of a movement exception holds for the movement, not for what was attached to it

Status: accepted. Issues: #83, CC10 #86.

The gate on contracts 0.5.0 (#83) found that an unexpected check-in or a foreign movement HQ had closed came back
under a new id when the movement's predecessor arrived later, because the exception attaches the predecessor when the
detector has it and rule 7 matched a closure on the attached set.

1. **The choice.** An `unexpected_check_in` or `foreign_movement` is about one movement, its `dispute_key` names
   that movement, and whether the movement is unexpected (rule 6) or foreign (rule 8) depends on its own fields. A
   counting resolution of the same `kind` and `dispute_key` closes it whatever its `transactions`; the predecessor
   is context for people. A fork still binds to its branch set (decision 006), because a new branch is a new
   claimant, and whatever a late predecessor does change (a second movement naming it) surfaces as a fork. HQ's view
   is tentative until a close (decision 007), so HQ decides again when a new fact could change its answer, and only
   then. Rejected: leaving it (a closed dispute reappears on HQ's reducer-driven queue as new, and tablets' copies
   that attached the predecessor never close); attaching only the movement (a stable id, but it changes the ids in
   every existing movement-exception fixture and drops the context HQ shows); a distinct `dispute_key` form for
   movement exceptions (would also separate them from a fork at the same movement, but rewrites the key in every
   fixture with a movement exception, and the schema pattern, for a case the `kind` already separates).
2. **What it costs.** A few lines in each reducer's rule 7 filter (Python, Swift). HQ's queue keys a movement
   dispute by `kind` and `dispute_key`, and its resolve closes every copy of that kind and key. A consumer that
   groups exceptions by `dispute_key` alone merges a fork at a flagged movement with the movement's own exception,
   so groups are by `dispute_key` and whether the kind is a fork's.
3. **When to revisit.** If a movement exception kind appears whose truth depends on more than the movement itself
   (Phase 1 allowances), or when Phase 2's close makes HQ's closures part of a settlement.
