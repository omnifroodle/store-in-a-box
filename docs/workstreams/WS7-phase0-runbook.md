# WS7: Phase 0 runbook, QR labels and the acceptance checklist

**Milestone:** M1  **Depends on:** WS2, WS3, WS4, WS5, WS6 (for the rehearsal; labels and the draft can start after CC2); WS8 part A (the words of the ledger beat)  **Label:** `ws:7-phase0-runbook`  **Agent type:** ws-mechanical
**Issue:** #18

The blueprint. The architect (`ws-architect`) writes it before any code is dispatched; the PR is judged against it.

## Scope

The paperwork that turns six workstreams into a demo that can be run twice the same way: the printed QR labels for
the seed units, the step-by-step Phase 0 runbook with every command, the reset script that puts the whole system
back to "packed nothing yet", and the acceptance checklist that maps `docs/SPEC.md` section 5 Phase 0 line by line
to a check someone can run. The milestone audit for M1 runs this checklist.

Left for later: the twelve-minute narrative runbook (Phase 1 onward; `docs/SPEC.md` section 12), throttling and
checkpoint beats, the deck.

## Files

Owned by this workstream:
- `docs/runbook/` (new: `docs/runbook/phase0.md`, `docs/runbook/phase0-acceptance.md`, `docs/runbook/reset.md`)
- `scripts/demo/` (new: `scripts/demo/labels.py`, `scripts/demo/reset_rehearsal.sh`, `scripts/demo/stage_oversell.sh`,
  `scripts/demo/README.md`)

Named edits in neighbours' code:
- `README.md`: in the table, change the Status row to point at `docs/runbook/phase0.md` once Phase 0 runs.
- `pyproject.toml`: add the PDF or HTML dependency `labels.py` needs only if it is not already present (prefer
  none: HTML with inline SVG QR codes printed from a browser needs only the `qrcode` package WS3 adds).

## Interfaces

- `python scripts/demo/labels.py [--seed contracts/fixtures/seed/products.json] [--per-sku N] [--out labels.html]`:
  one label per unit `<SKU>#<serial>` for serials `001..N`, each label the SKU text, the serial, the product name
  and the QR of exactly the payload WS6 parses. Default `--per-sku` from D3 (recommend 5; 16 SKUs → 80 labels on
  Avery 5160-style sheets or equivalent, the layout is CSS in the file).
- `scripts/demo/reset_rehearsal.sh`: runs `python -m siab_capella reset-trip --trip $SIAB_TRIP --yes`,
  `python -m siab_capella seed --yes`, `curl -X POST $SIAB_BOX_STATUS_URL/bytes/reset`, and prints the manual steps
  left (on each tablet: Diagnostics → Rebuild derived state, or reinstall). Refuses without `--yes`.
- `scripts/demo/stage_oversell.sh <unit-id>`: `POST /api/stage/hq-sale` on the HQ app (WS5) and prints the
  transaction id and the dispute to expect.
- `docs/runbook/phase0.md`: pre-flight (box laptop on the travel router's LAN and `box/run.sh` up, HQ screen up,
  tablets paired, byte counter reset, labels on the table), then the beats in order with the exact command or gesture
  per step, what the audience should see, and which acceptance line it proves. Two setups (D7, #19), one laptop first:
  the **default** runs the HQ screen on the box laptop and cuts with `box/install/uplink.sh cut`; the **alternative**
  pulls the router's WAN cable and runs the HQ screen on a second machine with its own internet. Each beat that cuts
  says what to do in both. One beat
  is headed **Conflict-free by construction** (the staged oversell, `stage_oversell.sh` then the cable): its words
  are section 8, "On stage", of `docs/architecture/conflict-free-ledger.md` (WS8), copied in, not rewritten; a
  change the rehearsal forces goes back to the note as a `for-foreman` issue so the two stay one text.
- `docs/runbook/phase0-acceptance.md`: the eight Phase 0 acceptance lines from `docs/SPEC.md` section 5 as
  checkboxes, each with: how to perform it, the observable result (what the HQ screen or the tablet must show,
  the byte number to read), who can check it (owner-present or agent with `box`+`capella`), and the
  `needs-verification` issue numbers from WS2–WS6 it closes when it passes.

## Contract changes

none (reads `contracts/fixtures/seed/products.json`).

## Exit criteria

- [ ] `python scripts/demo/labels.py --per-sku 2 --out /tmp/labels.html` exits 0 and the file contains exactly
      `2 × <number of SKUs in the seed>` labels whose QR payloads match `^[A-Z0-9-]+#\d{3}$`; `pytest tests/demo`
      has `test_labels_count_and_payloads` decoding the QRs (with a pure-Python decoder or by checking the payload
      text the generator embeds next to each code).
- [ ] `shellcheck scripts/demo/*.sh` prints no errors; `reset_rehearsal.sh` without `--yes` exits 2 and writes nothing.
- [ ] `docs/runbook/phase0-acceptance.md` has one checkbox per Phase 0 acceptance line in `docs/SPEC.md` section 5
      (eight), each naming its check and who runs it.
- [ ] `grep -c "Conflict-free by construction" docs/runbook/phase0.md` prints at least 1, and the beat's text
      under that heading is the "On stage" section of `docs/architecture/conflict-free-ledger.md` (`diff` of the
      two blocks is empty apart from heading level and the runbook's step numbers).
- [ ] `[owner-present]` One full rehearsal of `docs/runbook/phase0.md` on the real devices, box and cluster, with the
      byte number, the conservation screenshot and the exception count recorded in the PR (no IPs, no hostnames).
      Expected to be filed as `needs-verification` and run in the owner verification session.
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

## Owner decisions
**Answered 2026-10-07** (closing comments on #6–#11): D1 yes (all Apple devices, free Apple account, repo public, macOS CI on every PR; decision 002); D2 yes, and featured in the demo (decision 001, WS8); D3 yes; D4: the box is a macOS laptop, the Pi on Debian Trixie is best-effort (decision 002); D5 yes; D6 yes, with the event renamed Richmond Riverfest (`trip-2026-10-18-riverfest`). Money is integer cents (decision 003). The lines below are the questions as asked; anything still open is marked.


- D3 (#8): labels per SKU and label stock (recommend 5 per SKU, Avery 5160 or any 30-up sheet; blocks dispatch: no).

## Verification plan

- The rehearsal itself: owner-present, with the foreman recording results in the `needs-verification` issues.
- Labels print and scan: owner-present (printer, stage light).
- Reset really resets: agent with `capella` and `box` runs `reset_rehearsal.sh` then WS5's conservation shows
  nothing packed and the box counter is zero.
- The staged oversell (#61): HQ already holds the pack, so its own copy of the dispute appears before the cable goes back
  in. At rehearsal, decide whether the HQ exception panel stays off the projector until the plug-in, and write the
  decision into `docs/runbook/phase0.md`. Owner-present.

## Tasks

Step by step (ws-mechanical):
1. `[any]` `labels.py` and its test. Accept: the labels criterion.
2. `[any]` `reset_rehearsal.sh`, `stage_oversell.sh`, `scripts/demo/README.md`. Accept: shellcheck and the refuse test.
3. `[any]` Draft `docs/runbook/phase0.md` and `phase0-acceptance.md` from the merged WS2–WS6 READMEs and port docs.
   Accept: eight checkboxes, every command copied from a merged README or port doc (no invented flags).
4. `[owner-present]` Rehearsal; fix the runbook where it was wrong. Accept: the rehearsal criterion or its issue.
5. `[any]` **PR.** One PR, `Closes #<issue>`; `needs-verification` issues filed and linked from "Not verified".
   Expected size: about 300 lines of code (tests and fixtures not counted; split the issue if it is over about
   1,500).

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
