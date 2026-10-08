# Review gate log

One line per gated PR, and per baseline or milestone audit (see "The review gate" in FOREMAN.md). Read it with the owner
after five or six PRs and tighten or loosen the bar.

| PR | Rounds | Blocking raised | Upheld | Follow-ups filed | Escalated |
|---|---|---|---|---|---|
| #22 contracts 0.1.0 (foreman-authored, CC1–CC4) | 2 | 1 (a non-hq writer could resolve a fork: sync create path and reducer) | 1 | #26 (follow-ups), #27 (conservation `holds` is an identity, to the architect) | no |
| #30 contracts 0.2.0 (foreman-applied CC5, conservation `holds` can fail) | 2 | 1 (`untraced` defined two ways; a null-root take turned a row false mid-replication) | 1 | #31 (follow-ups); the foreman filed #32 (false root fork after a null-root take) | no |
