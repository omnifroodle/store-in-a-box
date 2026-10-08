# Review gate log

One line per gated PR, and per baseline or milestone audit (see "The review gate" in FOREMAN.md). Read it with the owner
after five or six PRs and tighten or loosen the bar.

From 2026-10-08 to 2026-10-12 the reviewer runs on Sonnet as a trial (the owner wants to see what it misses and whether it files spurious findings). Add `, model` to the PR cell for those rows, and note any finding later judged spurious or any defect a gate missed. Gates up to and including #71 ran on Opus.

| PR | Rounds | Blocking raised | Upheld | Follow-ups filed | Escalated |
|---|---|---|---|---|---|
| #22 contracts 0.1.0 (foreman-authored, CC1–CC4) | 2 | 1 (a non-hq writer could resolve a fork: sync create path and reducer) | 1 | #26 (follow-ups), #27 (conservation `holds` is an identity, to the architect) | no |
| #30 contracts 0.2.0 (foreman-applied CC5, conservation `holds` can fail) | 2 | 1 (`untraced` defined two ways; a null-root take turned a row false mid-replication) | 1 | #31 (follow-ups); the foreman filed #32 (false root fork after a null-root take) | no |
| #35 contracts 0.3.0 (foreman-applied CC6, blind movements) | 1 | 0 | 0 | #36 (fixture gaps), #37 (two rule-2 edges, to the architect) | no |
| #43 WS2 Capella and sync functions | 1 | 0 | 0 | #53 (7 non-blocking items) | no |
| #52 WS3 Edge Server box | 1 | 0 | 0 | #54 (6 non-blocking items) | no |
| #55 contracts 0.3.1 (foreman-applied CC7) | 1 | 0 | 0 | #56 (5 non-blocking items) | no |
| #60 WS1 custody ledger reference (re-check of the 0.4.0 update, Sonnet) | 2 | 0 | 0 | #67 (4 non-blocking items); author filed #58, #59 | no |
| #66 WS8 part A, the ledger story | 1 | 0 | 0 | #69 (non-blocking items) | no |
| #71 contracts 0.4.0 (foreman-applied CC8) | 1 | 0 | 0 | #72 (4 reducer ambiguities, to the architect), #73 (stale 0.3.1 text in WS1) | no |
