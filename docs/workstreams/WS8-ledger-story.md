# WS8: The conflict-free ledger, documented and on stage

**Milestone:** M1  **Depends on:** D2 (#7, answered) and CC3 (#4) applied, for part A; WS1 merged, for part B  **Label:** `ws:8-ledger-story`  **Agent type:** ws-design (part A) | ws-mechanical (part B)
**Issue:** #23 (part A); #24 (part B, filed as a second issue under the same label, branch `ws8b/ledger-story-code`)

The blueprint. The architect (`ws-architect`) writes it before any code is dispatched; the PR is judged against it.

## Scope

Decision 001 (D2, #7) made custody **conflict-free by construction**: every movement is an immutable `transaction`
written once by one device, each names its predecessor (`prev_txn`), counts are derived and never edited, a fork
(two movements with the same predecessor) is detected by one deterministic reducer that runs the same way on every
node, and a fork becomes an `exception` with both transactions attached. The owner called this a headline feature
of the design and asked for it to be well documented and called out at a high level in the demo. This workstream
is that documentation and that callout. It is words, pictures and a link checker, not product code.

**Part A, now** (ws-design; everything the audience or a reader sees):
1. A new architecture note, `docs/architecture/conflict-free-ledger.md`, the authoritative narrative of the
   pattern: immutable movements, `prev_txn` and the custody chain, forks as exceptions, the same reducer on every
   node, why not a replication-layer resolver (what Edge Server 1.1 and App Services actually offer), what the
   pattern costs, a worked example walked by hand through two golden fixtures, and the stage beat.
2. The `docs/SPEC.md` edits that follow from D2, as named one-paragraph edits (section 4.4 rewritten, section 8
   talking point 7, the section 11 open question closed, the beat-13 row in section 2, the App Services row in 3.0,
   the double-scan sentence in 4.1) and the three `trip-2026-10-18-maker-fair` examples renamed to
   `trip-2026-10-18-riverfest`.
3. The neighbouring architecture notes that still describe a "custom conflict resolver", corrected by named
   paragraph-sized edits that point at the new note, so the pattern is not contradicted one click away.
4. A high-level callout in `README.md` and a feature section on the product page (`site/index.html`), plus the
   page's other D2 and D6 consequences (the "MAKER FAIR" label in the compliance SVG becomes Riverfest; the resolver
   wording in the App Services section, footnote 8, the "On the box" column, the specs rows and the "Get it" text;
   footnote 10 and the box specs row say what D4 decided; the page's repository links point at the repository
   that exists).
5. The words for the demo beat ("Conflict-free by construction", the staged oversell) as a section of the note.
   **WS7 owns the runbook** (`docs/runbook/phase0.md`) and copies that section into it; WS8 never edits the runbook.
6. `scripts/check_links.py`, a stdlib-only link and citation checker, so "links resolve" and "the claims cite
   paths that exist" are commands rather than opinions.

**Part B, after WS1 merges** (ws-mechanical): the claims only real code can back. The note's "Where it lives"
table gains the rows for the Python reference reducer (`src/siab_ledger/`, `ports/ledger.md`) and, for whichever of
WS4 and WS5 have merged by then, the Swift port and the HQ reconciler; every path is checked by the citation
checker. Part A writes no path that does not exist at the time of writing, so nothing in it waits on WS1. If the
owner wants a "the same N lines on every node" number on stage, part B computes it with a command recorded in the
PR; the default is to make no line-count claim (see D8).

Left for later: the twelve-minute narrative runbook and the deck (Phase 1 onward, `docs/SPEC.md` section 12), the
allowance ledger story (Phase 1, when allowances join the ledger), a rewrite of `docs/architecture/couchbase-lite-custody.md`
beyond the named paragraph edits below (its Phase 0 content is otherwise right), a blog post, the rendered video for
the "Watch it happen" placeholder, and the clock-skew story (showcase 11, Phase 1).

## Files

Owned by this workstream:
- `docs/architecture/conflict-free-ledger.md` (new: the note)
- `scripts/check_links.py` (new: the link and citation checker; see Interfaces)
- `site/index.html` (the product page; the edits are named below, but the file is owned here for Phase 0)
- `site/styles.css` (only if the new feature section needs a style the page does not have; prefer none)

Named edits in neighbours' files (each is the paragraph, row or line named, nothing more):
- `README.md`: after "The beats", a short section **"The pattern underneath: a conflict-free ledger"** (four to six
  lines) linking to the note; beat 6 says "forks become exceptions with both sides attached"; the Architecture row
  of the table names the note.
- `docs/SPEC.md`:
  - section 2, beat 13: "Resolver wrote a third document with both sales" → the ledger wrote it; the "What it
    proves" cell becomes "Conflict-free by construction: a fork, not a conflict".
  - section 3.0, the Capella App Services row: "conflicts hand off to the application's resolver" → "custody data
    never conflicts; forks are found by the ledger on every node".
  - section 4.1: the `allocation::<id>` example renames the trip; the sentence "Two devices that both scanned the
    same unit produce a conflict the resolver turns into an exception" → a fork in the unit's custody chain that
    the ledger turns into an exception.
  - section 4.1a: the `allowance::<id>` example renames the trip (nothing else in 4.1a changes; the allowance
    ledger is Phase 1).
  - section 4.4 **Conflict policy**: rewritten in full (about the same length) to the conflict-free ledger:
    movements immutable, counts derived, forks detected by the reducer on every node, `exception` with both
    transactions and a `dispute_key`, `disputed` until HQ chooses a branch, last-write-wins for everything that is
    not custody or money, Couchbase Lite's `ConflictResolver` kept only for the rare same-document case named in
    decision 001. Ends with a link to the note.
  - section 7.3a: the `permit::<id>` example renames the trip.
  - section 8, talking point 7: "**Conflict-free by construction.** Two sales of the last unit are a fork in one
    unit's custody chain, found by the same reducer on every node; the fork becomes an exception with both sales
    attached. A double-scan the same way. No node ever has two versions of one document to choose between."
  - section 11: the open question "Does the Edge Server to App Services path support the custom conflict
    resolver..." becomes "Closed 2026-10-07: neither does; see decision 001 and the ledger note." (one line, kept
    in place so the list's history reads).
- `docs/architecture/overview.md`: the beats table row "Oversell becomes an exception | Custom conflict resolver"
  → "Conflict-free ledger | [conflict-free-ledger](conflict-free-ledger.md)"; the mermaid label "conflict handoff"
  → "exception handoff"; the "Why custody and not counts" paragraph gains one sentence and the link; the component
  list at the foot gains the note.
- `docs/architecture/app-services-sync.md`: the "Conflicts hand off to the resolver" paragraph and its bullets →
  one paragraph, "Custody data does not conflict", saying what App Services does with a conflicting push (rejects
  it; resolution is the client's) and that the demo never relies on it, with the link; the talking point "A
  conflict here is not a bug to resolve..." → "A fork here is not a conflict to resolve. It is an exception to
  review, with both sides attached."; the alternatives row "Server-side last-write-wins" names the ledger instead
  of the resolver; the mermaid `trip:maker-fair` → `trip:trip-2026-10-18-riverfest`.
- `docs/architecture/edge-server-box.md`: the "Runs the same conflict resolver as the cloud" paragraph → "Runs no
  custody logic" (the box moves documents; the tablets and HQ run the ledger; link); the mermaid node `CR` and its
  edge removed; the box is "a laptop in Phase 0, a Raspberry Pi where Edge Server supports its OS" in the opening
  paragraph and the "Lightweight on purpose" paragraph (D4).
- `docs/architecture/device-to-device-sync.md`: the "Conflicts are rare by design" paragraph → forks: two devices
  that both take one unit have written two movements with the same `prev_txn`; whichever node sees both first
  writes the exception; link.
- `docs/architecture/capella-reconcile.md`: "were created by the resolver at the venue" → "were created by the
  ledger on whichever node saw the fork first, and HQ's reconciler finds any the venue did not".
- `docs/architecture/couchbase-lite-custody.md`: the conservation SQL block (it sums `a.qty`, which CC3 removed)
  → the derived-count statement (count units whose latest movement names the custodian) or a two-line pointer to
  `ports/ledger.md`'s `conservation` once it exists (part B decides which; part A writes the pointer to the note);
  the sentences "Sales decrement the selling device's allocation" and "`txn:: + decrement`" in the mermaid → a
  sale is one more immutable movement, counts are derived; link.
- `docs/workstreams/WS7-phase0-runbook.md`: no edit by this workstream (the architect has already named the beat
  there; WS7 copies the words).

## Interfaces

**The note, `docs/architecture/conflict-free-ledger.md`**, follows the shape of the other notes (a one-paragraph
lede, a mermaid diagram, "How Store in a Box uses it", "Talking points", "Possible enhancements", "Alternatives and
trade-offs", "Related") and must have these `##` sections, in this order, with these headings:
1. **The pattern in one paragraph**: a unit's custody is a chain of immutable movements; a sale is a movement to
   `customer`; a count is the number of chains that currently end at a custodian; a fork is two movements with the
   same `prev_txn`; the reducer is the same on every node; a fork is an `exception`, never a lost or phantom unit.
2. **Why not a conflict resolver**: what the spec assumed (section 4.4 as it was); what was checked on 2026-10-07
   (Edge Server 1.1 has no application conflict hook; App Services rejects a conflicting push and leaves
   resolution to Couchbase Lite on the client); why a resolver that runs on some nodes makes "same answer in any
   merge order" depend on where the conflict is noticed; what Couchbase Lite's `ConflictResolver` is still used for.
   Cites `docs/decisions/001-ledger-not-resolver.md`.
3. **The documents**: `transaction` (kinds `check_out`, `check_in`, `sale`; `unit_id`, `from_custodian`,
   `to_custodian`, `prev_txn`, `hlc`, `device`), `allocation` (no `qty`; counts are derived), `exception` (`kind`,
   `dispute_key`, `fork_txn`, `transactions`, `branches`, `status`, `resolution`). Cites the three schemas under
   `contracts/schemas/store/` and the id conventions (`txn::<hlc>`, `exc::<detector>::<unit_id>::<hash8>`).
4. **The reducer**: the seven rules as the contract states them (forest by `prev_txn`; dangling roots are not
   errors; a fork is two or more movements sharing a `prev_txn`, `null` included, except a null-`prev` check-in;
   an unresolved fork makes the unit `disputed`; otherwise the leaf with the greatest `hlc` holds; reduction is a
   pure function, order of arrival never changes the result; an unexpected check-in stands and raises its own
   exception; detectors create, HQ resolves). Written from `docs/decisions/001-ledger-not-resolver.md` and the
   fixtures, in prose, not copied from `docs/workstreams/WS1-ledger.md` (blueprints are not citations).
5. **Worked example**: `contracts/fixtures/ledger/double-scan.json` and `contracts/fixtures/ledger/oversell-hq.json`
   walked by hand: the transactions, the chain, the fork, the exception id and `dispute_key`, the counts, and why
   `conservation` still holds with `disputed: 1`. A third short walk of `merge-order-independent.json` says what
   "any order" means. The expected values quoted must equal the fixtures' `expected` blocks (the citation checker
   does not check values; the reviewer does).
6. **The same reducer on every node**: tablets (Swift), HQ (Python), the box (none; it moves documents), and that
   the golden fixtures, not either language, are the source of truth. Part A names the languages and the
   workstreams; part B adds the table rows with paths. Section carries the table **Where it lives** with columns
   Artifact, Path, Checked by.
7. **What it costs**: counts are queries, so the Shelf screen needs a derived local view; several detectors may
   write their own copy of one dispute, so HQ groups by `dispute_key`; two reducer implementations kept in step by
   fixtures; `disputed` units are off the shelf until HQ decides; HLCs, not wall clocks, order the leaf.
8. **On stage: Conflict-free by construction**: the beat, written to be read aloud and copied by WS7: pre-condition
   (a unit the box holds; the HQ sale staged with WS5's control), the three actions (fire the staged HQ sale; plug
   the cable in; open the exception on the HQ screen and show both branches), what the audience sees (the
   exception's two `branches`, the unit `disputed` on the Shelf, conservation still `holds`), the one sentence to
   say (D8), and the two follow-ups if asked ("where did the resolver run?" and "what if the tablet is still out
   of range?"). Sixty to ninety seconds.
9. **Talking points**, **Possible enhancements**, **Alternatives and trade-offs**, **Related** as in the other notes.
   The alternatives table has rows for last-write-wins counts, CRDT counters, a replication-layer resolver, and a
   central lock.

**The product page section** (`site/index.html`): one new `<section class="feature">` with `id="ledger"` between
"Custody, not counts" and "Device-to-device sync" (it is the pattern the next two sections rely on), kicker
"Conflict-free by construction", a headline of the implementer's choosing that says two sales of the last unit
become one exception and no node ever has two versions to choose between, a `.bignum` with `2` branches kept /
`0` winners picked (or equivalent; the number is the hook), a `.facts` list (immutable movements, `prev_txn`, same
reducer everywhere), a `.more` link to the note on GitHub, and a `figure.card` SVG in the page's existing style
(the crate palette and fonts): one unit's chain `pack → sale (tablet A)` and `pack → sale (HQ)` drawn as a fork,
with an `exception` box holding both. A new footnote replaces footnote 8's open question with what was checked.
Every GitHub link on the page uses the repository that exists (`omnifroodle/storeinabox`, or the name the owner
gives in D9).

**`scripts/check_links.py`** (stdlib only, no network; Python 3.12):
```
python scripts/check_links.py [--root .] [FILE ...]
    FILE defaults to README.md, docs/**/*.md, site/index.html.
    For each relative link ([text](path), <a href="path">, mermaid-free): the target file exists (anchors ignored).
    For each https://github.com/<owner>/<repo>/blob/<branch>/<path> link: <path> exists in the checkout.
    Other absolute URLs are listed, not fetched.
python scripts/check_links.py --cite FILE
    Every backticked token in FILE that looks like a repository path (contains "/" and its first segment is a
    directory at the root: contracts, docs, src, ports, app, scripts, site, sync, box, tests) must exist.
Exit 0 when nothing is missing; otherwise one line per miss, "<file>:<line>: <target>", exit 1.
```
The checker is a quality gate for every later docs PR; later workstreams may add it to CI (not this one).

**The runbook beat** is WS7's interface: `docs/runbook/phase0.md` carries a beat headed "Conflict-free by
construction" whose words are section 8 of the note, copied. WS7's blueprint names that edit.

## Contract changes

none. The note cites `contracts/` as applied by CC3; it changes nothing there.

## Exit criteria

Part A:
- [ ] `node scripts/build-site.mjs` prints `Built _site/` and exits 0.
- [ ] `grep -rni "maker.fair" README.md docs site` prints nothing (exit 1).
- [ ] `grep -rn "conflict resolver" README.md site docs/SPEC.md docs/architecture docs/runbook 2>/dev/null` prints
      only lines in `docs/architecture/conflict-free-ledger.md` (the note may name the rejected alternative; no
      other audience-facing file may still describe one).
- [ ] `grep -c 'id="ledger"' site/index.html` prints 1, and `grep -c "MAKER FAIR" site/index.html` prints 0.
- [ ] `python scripts/check_links.py` exits 0 (every relative link in `README.md`, `docs/**/*.md` and
      `site/index.html`, and every GitHub blob link, resolves to a file in the checkout).
- [ ] `python scripts/check_links.py --cite docs/architecture/conflict-free-ledger.md` exits 0 (every backticked
      repository path in the note exists).
- [ ] `pytest tests/docs` passes; includes `test_check_links_flags_missing_relative_target`,
      `test_check_links_resolves_github_blob_link_to_checkout`, `test_cite_flags_missing_path` and
      `test_cite_ignores_non_path_code_spans` (a code span such as `prev_txn` or `trip:<trip-id>` is not a path).
- [ ] The note has the nine `##` sections above, in order: `grep -n "^## " docs/architecture/conflict-free-ledger.md`
      lists them (the reviewer compares headings to the Interfaces list).
- [ ] `grep -c "trip-2026-10-18-riverfest" docs/SPEC.md` prints 3 (the three renamed examples).
- [ ] `ruff check scripts/check_links.py tests/docs` prints no errors.
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

Part B (its own PR, after WS1 merges):
- [ ] `python scripts/check_links.py --cite docs/architecture/conflict-free-ledger.md` exits 0 with the "Where it
      lives" table now naming `src/siab_ledger/` and `ports/ledger.md` (and `app/` and `src/siab_hq/` rows for
      whichever of WS4 and WS5 have merged).
- [ ] `python -m siab_ledger check` prints `PASS double-scan`, `PASS oversell-hq` and `PASS merge-order-independent`
      (the fixtures the note walks), run on the merged default branch and pasted in the PR.
- [ ] Every number in the note that describes the code (if D8 asks for one) is produced by a command recorded in
      the PR next to its output.
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

## Owner decisions
**Answered 2026-10-07** (closing comments on #6–#11): D1 yes (all Apple devices, free Apple account, repo public, macOS CI on every PR; decision 002); D2 yes, and featured in the demo (decision 001, WS8); D3 yes; D4: the box is a macOS laptop, the Pi on Debian Trixie is best-effort (decision 002); D5 yes; D6 yes, with the event renamed Richmond Riverfest (`trip-2026-10-18-riverfest`). Money is integer cents (decision 003). The lines below are the questions as asked; anything still open is marked.


- D8 (#20): the pattern's name on stage and whether to quote a code size. Recommend: the name
  is **"Conflict-free by construction"** (decision 001 already uses it; it is the section-8 heading, the page
  kicker and the runbook beat), the one sentence is "Two sales of the last unit are not a conflict. They are a fork
  in one unit's history, and the fork is the exception, with both sales attached.", and **no line count** is quoted
  on stage or on the page (line counts rot; "the same rules, checked by the same fixtures, on every node" does
  not). Blocks dispatch: no; the recommendation applies if unanswered.
- D9 (#21): the product page links to `github.com/omnifroodle/store-in-a-box`, but the
  repository is `omnifroodle/storeinabox`, so every "How it works" link on the page is dead. Recommend: point the
  page at `omnifroodle/storeinabox` now; if the owner intends to rename the repository, say so and the page uses
  the new name instead. Blocks dispatch: no; the recommendation applies if unanswered.

## Verification plan

- How the note reads to the audience it is for (an SE who will present it, a developer who will fork it): the
  owner reads it once and comments on the PR. Owner.
- The product page renders at phone width and at projector size with the new section and SVG, in light mode
  (the page has no dark mode): serve `_site/` and open it; an agent with a browser can check layout, the owner
  checks legibility and taste. Agent with a browser (layout); owner (taste).
- The stage beat's timing and the sentence out loud: WS7's rehearsal (owner-present); any rewording goes back into
  the note, not only the runbook, so the two stay one text.
- Part B's claims match the merged code: the milestone audit for M1 re-runs the `--cite` check and the fixture
  passes on the tagged commit. Milestone audit.
- GitHub Pages publication: `README.md` names `.github/workflows/pages.yml`, which does not exist in the checkout;
  whether the built `_site/` is published anywhere is outside this workstream and is noted to the foreman, not
  verified here.

## Tasks

Part A, milestones and acceptance tests (ws-design):
1. `[any]` `scripts/check_links.py` and `tests/docs`. Accept: the `pytest tests/docs` criterion; running the checker
   on the untouched checkout prints the dead GitHub links (that is the baseline the rest of the PR fixes).
2. `[any]` The note, sections 1 to 9, with the two fixture walks computed by hand from the fixture files (not from
   any implementation). Accept: the heading and `--cite` criteria.
3. `[any]` The SPEC edits, the neighbouring note edits, the README section. Accept: the `maker.fair`, `conflict
   resolver`, riverfest-count and `check_links.py` criteria.
4. `[any]` The product page section, SVG, footnote and link fixes; `node scripts/build-site.mjs`. Accept: the site
   criteria.
5. `[any]` **PR.** One PR, `Closes #<part A issue>`; `needs-verification` issues filed and linked from "Not
   verified" (expected: the owner's read, the page at projector size). Expected size: about 150 lines of Python
   (the checker) plus about 450 lines of Markdown and HTML (tests not counted; well under the 1,500 cap).

Part B, step by step (ws-mechanical), dispatched only after WS1 has merged:
1. `[any]` Add the "Where it lives" rows for `src/siab_ledger/` (the reducer module and the CLI) and
   `ports/ledger.md`; add rows for the Swift port and the HQ reconciler only if WS4 or WS5 have merged. Accept:
   `--cite` exits 0.
2. `[any]` Replace the conservation pointer in `docs/architecture/couchbase-lite-custody.md` with the operation
   `ports/ledger.md` names, if part A left a pointer. Accept: `check_links.py` exits 0.
3. `[any]` If D8 asked for a size number, compute it and record the command; otherwise confirm the note makes no
   such claim. Accept: the part B criteria.
4. `[any]` **PR.** One PR, `Closes #<part B issue>`. Expected size: under 60 lines.

## Rules
- Code against `contracts/` and `ports/`; fake your neighbours.
- Deadline, timeout and retry tests use virtual time (a fake clock or a virtual-time event loop), not wall-clock
  sleeps: wall-clock races pass locally and flake on CI.
- Generated code is regenerated by its script, never edited by hand.
- Do not edit `contracts/` -- open a `contract-change` issue for the foreman.
- Stay inside the Files list above; an edit you need outside it gets a `for-foreman` issue first.
- Work in your own git worktree/branch `ws<N>/<topic>`; one PR per issue; CI must be green.
- Notes, questions and decision requests for the foreman: file an issue with the `for-foreman` label (see FOREMAN.md).
  Do not leave them only in PR comments.
