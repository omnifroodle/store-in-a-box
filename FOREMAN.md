# FOREMAN

The foreman (a human or an agent) keeps the workstreams moving. The foreman owns the shared contracts
(`contracts/`), dispatches the work, routes the inbox, records decisions and keeps the board honest. Workstream
agents own their own directories. **The owner merges PRs**; the foreman never runs `gh pr merge` unless the owner
asks it to merge that PR (the request covers that PR only, not the next one).

## Roles
| Role | Who | Does | Does not |
|---|---|---|---|
| Foreman | the main session | board, dispatch, inbox routing, contract changes, decisions log, consulting the owner | review code it dispatched; merge |
| Architect | `ws-architect` (fable, effort high) | blueprints in `docs/workstreams/` before dispatch; answers design questions from the inbox | write code |
| Workstream agent | `ws-design` (opus, high) or `ws-mechanical` (sonnet, medium) | builds one issue to its blueprint, one PR | edit `contracts/` or files outside the blueprint's Files list |
| Reviewer | `ws-reviewer` (opus, effort high) | the review gate on PRs; root cause analysis on bugs; milestone audits | fix what it finds |
| Owner | a person | decisions, merges, the verification session | |

All four agent types are defined in `.claude/agents/`, which is where model and effort are set; the Agent call can
override `model` but not effort. Without a type the agent is `general-purpose` and inherits the foreman's model. When a
case is borderline, choose the type by where a wrong call would cost most.

## Notes to the foreman (the inbox)
Anything a workstream wants the foreman to see goes in a **GitHub issue labelled `for-foreman`** (use the "Note for the
foreman" issue template). PR comments are not an inbox: they are easy to post after a merge and nothing notifies the
foreman. A PR body may carry a "Notes for the foreman" section, but each note must also exist as a `for-foreman` issue.
Interactive sessions may also ping a live foreman session directly, but the issue is the durable record. A session on
a machine without `gh` hands its note to the owner to relay, or files a short-lived issue from another machine; there
is no inbox of files in the repo (a note written on a branch stays invisible to the foreman until it merges). The foreman
answers by commenting and closing the issue (or applying a `contract-change`). When the owner defers a note, swap
`for-foreman` for `deferred` so it stops showing as inbox on every pass.

## The loop
0. Read the inbox: `gh issue list --label for-foreman --state open`.
0a. Cross-project mailbox: read `inbox/storeinabox/` in the foreman breakroom and act on `status: open` notes. Rules are in
    the breakroom's `inbox/README.md`. Skip this step if the project is not registered there.
0b. Catch up on what happened outside the foreman's session: `gh pr list --state all --limit 10` (the owner and
    interactive sessions may merge on their own), then read the comments on recently merged PRs and open issues.
0c. Run `python3 scripts/board_check.py`. It counts as problems: closed workstream issues with unticked exit criteria,
    `Closes` PRs whose issue is still open, open inbox notes, merged PRs with comments posted after the merge (nothing
    notifies the foreman of those; read each, act on it, then reply with a comment containing `[foreman: seen]`), open
    PRs that edit files outside their blueprint's Files list, worktrees and local branches left after a merge, and a
    stale local checkout. It lists as information: open
    `needs-verification` issues per milestone, open PRs over the size cap (code lines only), and worktrees with no PR.
    Fix the board before dispatching.
1. `gh issue list --label "ws:*" --state open`: which workstream issues are ready (dependencies in
   `docs/workstreams/WS*.md` satisfied)? Check that each ready issue's blueprint still matches the latest owner
   comments. A blueprint that is out of date misleads a cheaper agent more than a stronger one, so fix it first.
   **Environments are per task.** Each task in a blueprint carries an environment tag (see "Environment" below). Never
   start a task in a session that does not have its environment: name it as the next task for a session that does, so
   the work is handed on rather than dropped. A single-instance environment (one device, one shared stack) runs one
   task at a time, and only the sessions the owner named may use it. An `owner-present` task waits until the owner is
   at the device.
2. **Blueprint first.** A new feature or integration, or a workstream whose spec has no Files, Interfaces and runnable
   Exit criteria sections, goes to `ws-architect` before any code: "Blueprint WS<N> (#<issue>)." Apply the
   `contract-change` issues it files and get the owner's answer on any decision it marks as blocking, then commit the
   blueprint. Small follow-ups and fixes with an obvious scope skip this step. A blueprint that implies more than
   about 1,500 changed lines of code (tests and fixtures not counted) is split into two issues, so each PR stays small
   enough for the gate to mean something. When two architects run in parallel, name the owner of each shared
   interface in both prompts.
3. For each ready issue, dispatch an agent in its own git worktree on branch `ws<N>/<topic>` with the prompt:
   "Read `docs/workstreams/WS<N>-*.md`, `contracts/`, `ports/`. Fake neighbours. Open one PR."
   Pick the agent type with `subagent_type`:
   - `ws-design`: the custody model and conflicts (allocations, allowances, split and merge, the conflict resolver, clocks, the conservation query), sync topology (sync function, channels and revocation, Edge Server config, peer-to-peer replication), agents and provenance (output contract, provenance checks, compliance eval, upsell search, on-box prompts) and clerk-facing UX (anything the audience sees on stage), and any work where the agent must make judgement calls the blueprint does not
     settle.
   - `ws-mechanical`: follow-ups, docs, plumbing, lint, small fixes, where the blueprint already names the change.
   Keep the agent's id: gate findings go back to it.
4. Check each PR: CI green, exit criteria ticked, no edits to `contracts/` unless a foreman-approved
   `contract-change`, every line under "Not verified" has its `needs-verification` issue, and a scan of the diff for
   secrets, hostnames, IPs and local paths. Then run the review gate (below) on the PRs that need it.
5. Report to the owner: PR URL, CI status, the gate verdict, and anything unverified. **Test the combination:** when
   two open PRs touch the same file, run the tests on them merged together (a scratch branch with both merged; a clean
   textual merge is not enough) before telling the owner both are safe. The owner merges. After the merge, pull the
   default branch, tick the exit-criteria boxes, close the issue, and clean up: `git worktree remove <path>`, then
   `git branch -D` the `ws<N>/<topic>` branch and any agent worktree branch. Remove reviewer worktrees right after each
   gate: they hold detached checkouts and can block the foreman's own.
6. Record any non-obvious decision in `docs/decisions/NNN-title.md` (see `docs/decisions/000-template.md`).

**Recurring steps** (every few passes, or when the counts in `board_check.py` grow):
- **Follow-up sweep.** The gate files one follow-up issue per PR, every time. Batch the open follow-ups by area into a
  few `ws-mechanical` (or `ws-design`) dispatches, so they do not pile up behind new work.
- **Owner verification session.** Nearly every PR adds `needs-verification` issues and many need the owner's eyes or
  ears. Schedule a session with the owner whose only job is to work through the ones only the owner can check: the
  owner runs or watches each check, the foreman records what was seen in the issue and closes it (or files a bug).
  Items an agent with the right device or service can check go to that agent instead (see "Verification debt").
  Exit scripts that announce each operator step and wait for the event they expect keep these sessions short.

## The review gate
The reviewer audits a PR cold, before the owner merges. The rules below exist to stop review-edit-review loops: the
gate costs at most one review, one fix pass and one re-check per PR.

- **Which PRs.** Every `ws-design` PR, and any PR that touches `contracts/` (schemas, golden fixtures and the seed and policy data derived from them), the App Services sync function, channel config or conflict resolver, the Edge Server or Capella config, or the agent prompts, tool definitions, provenance checks or gold set. Mechanical, docs and lint PRs skip
  the gate unless the foreman has a specific doubt.
- **Dispatch.** `ws-reviewer` with "PR gate: #<pr> (issue #<n>)." The foreman does not pass on its own view of the PR
  or the author's explanation.
- **The blocking bar.** Only four things block a merge:
  1. an exit criterion that is ticked but not met;
  2. a bug with a concrete failing scenario (inputs or state, and the wrong output or crash);
  3. an edit outside the blueprint's Files list, or an unapproved edit to `contracts/`;
  4. anything that weakens an access-control check (channel scoping, tablet revocation and purge, PII filtering, encryption at rest), a provenance check (`grounded`, `fresh`, `jurisdiction_match`; no claim marked `verified` without evidence) or the offline-first rule (nothing in the venue waits on Capella; no operation blocks on a link).
  Everything else is filed by the reviewer as one follow-up issue and the PR proceeds.
- **One fix round.** On `BLOCKED`, resume the original workstream agent (SendMessage, its context intact) with the
  numbered findings. It fixes only those and replies to each. If the original agent no longer exists (the session
  ended, the context is gone), dispatch a fresh agent of the same type on the same branch with the PR, the blueprint
  and the numbered findings, and the same instruction: fix only these.
- **Re-check, not re-review.** Dispatch `ws-reviewer` with "Re-check: #<pr>, findings 1..k, fix commits <a>..<b>." It
  looks only at the listed findings and the fix diff.
- **Then the owner.** If anything is still open after the re-check, the reviewer escalates with both positions and the
  owner decides. There is never a third round.
- **Blueprint disputes leave the PR.** If the reviewer thinks the design is wrong, it files an issue for the
  architect. The PR is judged against the blueprint as dispatched.
- **The reviewer never fixes.** Findings go back to the author; follow-ups become issues for a later dispatch.

**Root cause analysis.** For a bug found after merge, dispatch `ws-reviewer` with "RCA: #<issue>." It reproduces the
bug, names the cause and the process step that let it through (blueprint gap, missing exit criterion, a fake that hides
the behaviour, a review miss, an unverified item), and proposes the test or blueprint change that closes the hole. The
fix is a separate dispatch.

**The review log.** Add one line per gated PR (and per audit) to `docs/review-log.md`: PR, rounds (1 or 2), blocking
findings raised, findings upheld, follow-up issues filed, escalated or not. After five or six PRs, read the log with the
owner and tighten or loosen the bar.

**Adopting the gate on an existing codebase: the baseline audit.** Everything merged before the gate has never been
reviewed. When the gate is adopted, dispatch one `ws-reviewer` per risky area ("Baseline audit: <area>, paths <...>.")
to apply the gate's blocking bar to the code already on the default branch. Each blocking finding becomes its own `bug`
issue with a reproduction, fixed through normal gated dispatches; everything else goes in one follow-up issue per area.
Log each audit in `docs/review-log.md`.

## Contract changes
Changes are additive and optional where possible. Bump the contract version, update the fakes, and write a decision
note. Workstreams rebase onto the new version. The architect files the changes a blueprint needs as `contract-change`
issues; the foreman applies them before dispatch.

Generated code (types, clients, stubs) is regenerated by its script, never edited by hand. If any operational data (a
seeded document, a config record) is derived from the contract fixtures, changing that value in the live system is a
contract change, and a re-seed overwrites a live edit: diff the live value against the fixture before re-seeding.
Contracts here are schemas with golden fixtures, not code: one JSON Schema per collection (`docs/SPEC.md` section 4.2)
under `contracts/`, with golden fixtures that every implementation must pass (the tablet app, the sync function, the
conflict resolver on the box and in App Services, the agents' output contract). The tablets, the box and Capella are
written in different languages, so the fixtures, not any one language's types, are the source of truth.
- Nothing is generated from the contracts yet. If a blueprint adds generated types, it names the script that
  regenerates them here and adds a CI check that fails when generated output or fixtures are stale.
- Seed and policy documents (`policy`, `jurisdiction`, the catalog subset, the gold set) are derived from the fixtures.
  Editing one in the live Capella bucket is a contract change, and a re-seed overwrites the live edit.

## Config that matters
After changing any setting that controls spend or safety (a budget cap, a rate limit, a moderation threshold, a
feature flag that exposes something), read it back from the running system (a status endpoint, a log line, a CLI that
prints the effective value), not from the file you edited. "Set" is not "in effect": a process may read only its
environment, an older default, or a different file.

## Scheduled passes
A report-only foreman pass can run on a schedule. An unattended run can stall on a permission prompt nobody sees, and a
stalled run can block the runs after it. So run the scheduled task once by hand first (approve the tools it needs),
then check the first scheduled run itself, not only the first manual one: it finished, and the next run started.
This project runs a scheduled report-only pass: it reports the board and the inbox and dispatches nothing.

## Usage
Plan usage is one pool for the whole account, shared by every project, so it is not logged per repo. Keep one
user-level log (`usage-log.md` at the root of the foreman breakroom), one line per snapshot: time, project tag, the short-window and weekly figures, and
what ran in between. Take a snapshot before and after anything large (an audit, a design build, a batch of dispatches)
and pace new work against the account-wide figure.

## Milestones
- **M0**: foundation merged, board populated. The architect blueprints Phase 0 into workstreams, the foreman files
  their issues, and a setup PR adds the stack choice, CI and `contracts/`.
- **M1**: Phase 0, the skeleton with no AI (`docs/SPEC.md` section 5): custody by scan, selling with the uplink cut,
  tablets consistent with the box off, a one-level split and merge, a staged oversell, the conservation query holding.
- **M2**: Phase 1, sell well (edge AI). The cut line for a first showing.
- **M3**: Phase 2, reconcile and rejoin (cloud AI).
- **M4**: Phase 3, place (planning agents, compliance eval, Agent Catalog).
Phase 4 (stretch) gets a milestone only when the owner picks items from it.

**Before tagging a milestone**, all three hold:
1. Its workstream issues are closed and `board_check.py` is clean.
2. It has no open `needs-verification` issue (see below).
3. A milestone audit says `READY`: dispatch `ws-reviewer` with "Milestone audit: M<n>." It runs the system end to end
   on live services where the environment has them, not only fakes, and works through the verification issues it can
   check itself.

## Verification debt
"Not verified" is work, not a footnote. Each thing a workstream could not verify (live services, a real browser or
device, how something looks or sounds) is an issue with the **`needs-verification`** label and the workstream's GitHub
milestone, saying how to check it and **who can check it**: the owner (eyes, ears, taste, a decision), or an agent
with the right environment (a device, a live service). The author files them and links them from the PR's "Not verified" section; the
foreman checks at step 4 that every unverified line in the PR has its issue. Closing the workstream issue does not
close them.
- Split the debt by who can pay it. The owner verification session takes only the items that need the owner; the
  items an agent with a device or service can check are dispatched to a session with that environment (or left to the
  milestone audit), so they do not wait for the owner.
- Whoever checks it (the owner in a verification session, the milestone audit, a later workstream) comments with what
  they ran and saw, then closes it.
- A milestone is not tagged while it has an open `needs-verification` issue. To carry one past the tag, the owner moves
  it to a later milestone; the foreman does not.

## Branch protection
Protect the default branch: require the CI test check to pass before a PR merges. Do not require branches to be up to
date, so parallel workstreams do not have to rebase in turn (which is why "test the combination" in step 5 matters).
If the owner agrees, admins may push foreman-owned docs (decisions, this file, blueprints) straight to the default
branch; code always goes through a branch and a PR.

## Environment
No code yet; the stack is chosen in M0. The demo runs on three tiers (`docs/SPEC.md` sections 3 and 9.2):
- **Capella**: one cluster with App Services, Search, Columnar, Eventing, AI Services and Agent Catalog. Credentials
  come from the environment (`.env`, never committed); name the variables here once M0 defines them.
- **The box**: Couchbase Edge Server and a small model runtime on a Raspberry Pi 5 (8 GB) or a laptop.
- **Tablets and a phone**: two or three tablets and one phone running the Couchbase Lite POS app, plus a travel
  router or hotspot for the terrible-link mode.
Code, schemas, fixtures and unit tests against fakes run anywhere (`any`). `gh` is available in every session.

Environment tags used on tasks: `any` (any session), `<machine or device>` (only a session that has it), `owner-present`
(needs the owner at the device). Single-instance environments and who may use them:
- `box`: the one Edge Server box. One task at a time; only the foreman session, or a session the foreman names in the
  dispatch, may use it.
- `capella`: the one Capella cluster and App Services endpoint. Same rule. Tasks that only read from it still take the
  slot, because a re-seed or sync-function deploy by another task changes what they see.
- The tablets and the phone are `owner-present`: the owner holds them, and the cable-pull, split and merge beats are
  checked with the owner at the devices.
