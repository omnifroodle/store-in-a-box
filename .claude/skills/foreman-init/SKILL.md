---
name: foreman-init
description: Set up (or upgrade) the foreman pattern in this repository from the foreman-template kit. Use when the owner says "set up a foreman", "foreman init", "cold start a foreman", or asks to adopt the foreman pattern in a new or existing project. Asks the owner for the choices that cannot be defaulted (agent models and effort, inbox, environments, contracts), fills in the templates, creates labels, and registers the project in the foreman breakroom.
---

# foreman-init

Sets up the foreman pattern in the current repository. Works in two cases:
- **A repo created from the template** (`gh repo create <name> --template omnifroodle/foreman-template`): the files are already
  here, with `{{PLACEHOLDERS}}` to fill in.
- **An existing repo**: copy this skill folder into the repo (or clone the template next to it), then run it. It adds only
  what is missing.

## Rules
- **Never overwrite an existing file.** Check with `test -e` first. If a file already exists (an existing `FOREMAN.md`,
  PR template, `scripts/board_check.py`), show the owner the difference and ask; merge by appending if they agree.
- **Map, do not duplicate.** Where the project already has an equivalent of a kit file (step 0), adapt the kit to it
  instead of adding a parallel file.
- Do not commit secrets, hostnames, IPs or local paths into the templates.
- Do everything on a branch `foreman/init` and open one PR. The owner merges.

**Dry run.** If the owner says "dry run" (or `/foreman-init --dry-run`), do step 0 and step 1, then print what step 2
would add, map and skip, file by file, and stop: no branch, no files, no labels, no breakroom notes.

## Step 0: inventory what the repo already has
Before asking anything, look for existing equivalents and show the owner a table: kit item, what the repo has, and the
plan (add, map, or skip). Look at least for:
- workstream briefs or specs (e.g. `docs/briefs/`, `docs/specs/`): map `docs/workstreams/` to them; set
  `BLUEPRINTS_DIR` (and, if the file names differ, `blueprint_for`) in `scripts/board_check.py`;
- decision records or ADRs (e.g. `docs/adr/`): map `docs/decisions/` to them;
- a PR template or issue templates: append the missing sections (exit criteria, not verified, notes for the foreman)
  rather than adding a second template;
- existing labels (`gh label list`): reuse an existing workstream label scheme (e.g. `ws:W1`) instead of `ws:<n>-<slug>`,
  and adjust the `WS<n>:` title check in `board_check.py` to match;
- ledgers, lessons logs, a review or status log, an existing inbox convention, CI workflows (for `{{SETUP_CMD}}` and
  `{{TEST_CMD}}`), and code generators (for the contracts questions).
Record each mapping in the PR body.

## Step 1: ask the owner (two AskUserQuestion rounds, at most 4 questions each)
**Round 1.**
1. **Agent models and effort**, for all four agent types. Recommend `ws-architect` = `fable`, effort high;
   `ws-reviewer` = `opus`, effort high; `ws-design` = `opus`, effort high; `ws-mechanical` = `sonnet`, effort medium.
   Reviews run on every gated PR plus audits, so they dominate the spend: in the project this kit comes from, reviews
   on the strongest model burned about a third of a weekly limit in under two days. Keep the strongest model for the
   architect, whose runs are rarer, and check the owner's weekly limits before choosing it for the reviewer.
   These fill `{{ARCH_MODEL}}`/`{{ARCH_EFFORT}}`, `{{REVIEW_MODEL}}`/`{{REVIEW_EFFORT}}`,
   `{{DESIGN_MODEL}}`/`{{DESIGN_EFFORT}}` and `{{MECH_MODEL}}`/`{{MECH_EFFORT}}`. Ask what counts as design-heavy *in
   this project* (for example: the core domain logic, the scoring or ranking rules, anything that changes what users
   see). This becomes `{{DESIGN_SCOPE}}`.
2. **Environments, per task.** Can any session run any task, or are some tasks tied to a machine, a device, a shared
   service, or the owner being present? Tag **tasks**, not workstreams: one workstream can span machines (code that
   runs anywhere, plus flashing or device tests that need one machine). Ask which environments are **single-instance**
   (one device, one shared stack) and who may use them (fills `{{SINGLE_INSTANCE_ENVS}}`), and whether any checks need
   the owner at the device (the `owner-present` tag). The rule in FOREMAN.md step 1 applies: never start a task
   without its environment; name it as the next task instead.
3. **Contracts.** Where the shared interfaces live (`{{CONTRACTS_DIR}}`, e.g. `contracts/` or `schemas/`), where the
   ports and fakes live (`{{PORTS_DIR}}`), and whether contracts are code (versioned constant plus decision note) or
   schemas with golden fixtures that every implementation must pass. Then three more:
   - Is any code generated from the contracts? Who regenerates it, and with which script (never by hand)?
   - Does CI fail when generated types or fixtures are stale? (If not, recommend adding that check.)
   - Is any operational data (a seeded document, a config record) derived from contract fixtures? If so, changing that
     value in the live system is a contract change, and a re-seed overwrites a live edit.
   The answers fill `{{CONTRACT_NOTES}}` (the script names, the CI check, the seeded data and where it lives).
4. **The review gate.** Which paths always go through the gate besides `ws-design` PRs (`{{GATED_PATHS}}`, e.g.
   "`src/auth/`, `src/billing/` or the deploy config"), and which checks a PR must never weaken
   (`{{GUARDED_CHECKS}}`, e.g. "an auth, permission, data-integrity or spend check").

**Round 2** (only the questions that apply).
5. **Baseline audit** (an existing repo with code already on the default branch). Offer it (FOREMAN.md, "Adopting the
   gate"): name the two or three riskiest areas and their paths, and after the setup PR merges the foreman dispatches
   one `ws-reviewer` per area. Recommend it: code merged before the gate has never been reviewed.
6. **Inbox from machines without `gh`.** The inbox is GitHub issues labelled `for-foreman`. If some sessions run where
   `gh` is not available, agree how their notes arrive: the owner relays them, or a short-lived issue is filed from
   another machine. Do not set up an inbox of files in the repo.
7. **Scheduled pass.** Will a foreman pass run on a schedule? If so, the owner runs it once by hand first and checks
   the first scheduled run (FOREMAN.md, "Scheduled passes").
8. **Usage log.** Where the user-level usage log lives (`{{USAGE_LOG}}`, outside every repo: for example a file in the
   foreman breakroom or in the home directory). Plan usage is one pool across projects, so every project writes to
   the same log with its project tag.

Also collect, from the repo where possible and from the owner otherwise: `{{PROJECT}}` (short name), `{{SETUP_CMD}}`
(copy it from the CI workflow so agents install what CI installs), `{{TEST_CMD}}` (the lint and test commands CI runs),
`{{MILESTONES}}` (M0 is always "foundation merged, board populated"), and `{{ENVIRONMENT}}` (toolchain, where `gh` is,
names of the secrets but never their values).

## Step 2: fill in and add files
Follow the step 0 mapping: a mapped item is adapted in the project's own file, not added.
| File | Notes |
|---|---|
| `FOREMAN.md` | Fill placeholders. Point its paths at the mapped directories from step 0. |
| `.claude/agents/ws-architect.md`, `ws-reviewer.md`, `ws-design.md`, `ws-mechanical.md` | `model` and `effort` in the frontmatter. Effort can only be set here. These govern subagents only; interactive sessions on other machines read FOREMAN.md and the blueprint instead. |
| `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/foreman-note.md` | As is, or append to the existing template. |
| `docs/workstreams/TEMPLATE.md`, `docs/decisions/000-template.md` | As is (or into the mapped directories). The template is the blueprint format the architect writes; keep the environment tag on each task. |
| `docs/review-log.md` | As is (the table header only). |
| `scripts/board_check.py` | Set `DRAFTS_DIR` if the project keeps draft posts, and `BLUEPRINTS_DIR` and the label and title patterns per step 0. |
| `scripts/setup_labels.sh` | Run it (it adds `needs-verification`, `bug` and `deferred` among others), then add one workstream label per workstream (or keep the existing scheme). |
| `.gitignore` | Add `.claude/worktrees/` if missing (agents' worktrees must never be committed). |

Then `grep -rn '{{' . --exclude-dir=.git --exclude-dir=foreman-init` must return nothing.

## Step 3: register in the foreman breakroom (if this machine has it)
The breakroom is an Obsidian vault; its path is `OBSIDIAN_VAULT_PATH` in `~/.obsidian-wiki/config`. If it is not
present (cloud session, another machine), skip this step and tell the owner to run it later from a machine that has it.
1. Read `concepts/foreman-pattern.md` and `inbox/README.md`.
2. Create `inbox/<project>/` (check it does not exist first).
3. Write a short note into each existing project's inbox (`inbox/<other>/YYYY-MM-DD-new-foreman-<project>.md`, frontmatter
   per `inbox/README.md`, `status: open`): what the project is, which choices it made in step 1, and that it started
   from the template. Append one `MAIL` line per note to `log.md`.
4. The vault is a git repo: commit the files you wrote (`git add <paths>`, never `-A`) with a message starting `<project>:`, then `git push`.

## Step 4: open the PR and report
PR title `Foreman setup from foreman-template`. The body lists the step 0 mapping, the choices from step 1, and anything
that was skipped or merged rather than copied. Tell the owner what to do next: merge; then, if chosen, the baseline audit (one reviewer per
named area); then the architect blueprints the workstreams and the foreman files their issues, which is milestone M0.
Also suggest protecting the default branch (FOREMAN.md, "Branch protection").

## Upgrading
When the template gains a lesson, run this skill again in an existing project (a dry run first is a good idea). Diff
each kit file against the project's copy, propose only the additions, and never replace local choices. Ask only the
step 1 questions whose placeholders are new since the project's last run (from v1 to v1.1: the per-task environment
tags and single-instance environments, the three contracts questions, the scheduled pass and the usage log).
