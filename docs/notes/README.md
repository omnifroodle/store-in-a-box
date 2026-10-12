# Shared notes

Facts one agent learned that the next one should know, and that the foreman need not act on. Anything that needs a
decision, a contract change, an edit outside a blueprint's Files list, or is a blocker goes in a `for-foreman` issue
instead (see `FOREMAN.md`, "Notes to the foreman" and "Shared notes").

Good notes: a toolchain or CI quirk, a service that behaves differently from its docs, why an approach was tried and
dropped, where a fixture or constant came from, a command that saves the next agent an hour.

## How to write one
- One file per note: `docs/notes/YYYY-MM-DD-<topic>.md`, added in your own PR. Never append to someone else's note
  or to a shared file, so parallel PRs do not conflict.
- This directory is outside every Files list and `scripts/board_check.py` allows it in any PR.
- Keep it short: what is true, how you know (a command, a link, a failing build), and which workstream or files it
  touches. No secrets, hostnames, IPs or local paths.

```
# Xcode on CI drops the memberwise init past a private property

- Seen: WS6, `ScanDebouncer`, the iOS CI build on Xcode 26.6.
- Do: give structs with a `private` stored property an explicit `init`.
- Touches: any Swift struct the iOS CI builds.
```

## What happens to notes
Every dispatched agent reads this directory before starting. In the follow-up sweep the foreman folds each note that
still matters into the blueprint, decision, architecture doc or agent definition where it belongs, and deletes the
note in the same commit. Git history keeps the original.
