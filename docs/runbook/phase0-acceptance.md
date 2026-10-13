# Phase 0 acceptance checklist

The eight acceptance lines of `docs/SPEC.md` section 5, "Phase 0: Skeleton (no AI)", one checkbox each. The M1
milestone audit runs this list. **Who** is `owner` (owner-present, real devices) or `agent: box+capella` (an agent
session with the box and the Capella cluster), and no line can be ticked from fakes alone. **Closes** names the
open `needs-verification` issues that line passing live lets the foreman close. Beats refer to
[`phase0.md`](phase0.md); record the observed numbers in the PR or issue, never IPs or hostnames.

- [ ] **1. Pack by scanning units out of the store onto the box; store on-hand drops per scan.**
  - How: beat 1. Tablet A, Custody, Pack, scan serials 001 and 002 of all 16 SKUs (32 units).
  - Result: on the HQ screen, each scan lowers that SKU's `store_on_hand` by one and raises `in_custody` for `box-07`
    by one; the totals after the pack are 32 fewer on hand. Screenshot the conservation table.
  - Who: owner (printed labels, camera); agent: box+capella for the HQ side.
  - Closes: #116, #89.
- [ ] **2. Tablets sell by scan against allocations with the box's uplink cut.**
  - How: beat 2. Cut the uplink (`box/install/uplink.sh cut`, or the WAN cable), take units, sell on both tablets.
  - Result: the status page shows UPLINK CUT, each sale shows the "Sold N units" banner on the tablet, and the byte
    counter stays at its pre-cut value.
  - Who: owner.
  - Closes: #116, #98, #49.
- [ ] **3. Tablets stay consistent with each other with the box powered off.**
  - How: beat 3. Stop Edge Server (`box/run.sh --edge-only` terminal, Ctrl-C), sell on each tablet.
  - Result: each tablet's Shelf shows the other's sale within seconds; Diagnostics lists the other as a mesh peer.
    Needs Enterprise Edition builds (`app/README.md`).
  - Who: owner, two physical iPads.
  - Closes: #98.
- [ ] **4. Tablet B takes eight off the box, leaves range, sells three, returns, scans five back; box and tablet agree
  without the cloud; the box kept selling.**
  - How: beat 4, with the uplink cut throughout.
  - Result: after the return, tablet B and the box (read on tablet A's Shelf, the box column) show the same counts: 5
    back in the box allocation, 3 sold; tablet A's sales during the absence all succeeded.
  - Who: owner.
  - Closes: #116, #98.
- [ ] **5. Restoring the uplink reconciles with a visible byte count under 100 KB for a day of fifty transactions.**
  - How: plug in (`box/install/uplink.sh restore`, or the WAN cable) after at least fifty movements since
    `POST /bytes/reset`; wait for replication `idle`.
  - Result: `bytes.out + bytes.in` from the box's `/status` is under 102,400. Observed: `____ B out, ____ B in`,
    `____` movements (placeholder: filled from #46's live run). The number is shown large on the status page.
  - Who: agent: box+capella reads the number; owner confirms the readout is visible on stage.
  - Closes: #46, #49.
- [ ] **6. The conservation query holds before, during and after, including while tablet B is out of range.**
  - How: keep the HQ screen up through beats 1 to 7; screenshot it before the pack, after beat 2, during beat 4
    (tablet B away), and after the plug-in.
  - Result: the indicator reads `HOLDS · live` in each screenshot (`holds: true` from `GET /api/conservation`); with
    the oversell it reads `holds` with one unit disputed. Failing rows say why (`overdrawn by N`, `N untraced`).
  - Who: agent: box+capella for the numbers; owner for the projector (HQ screen legible, #92).
  - Closes: #89, #92.
- [ ] **7. One staged oversell produces one exception document with both transactions.**
  - How: the Conflict-free by construction beat. `scripts/demo/stage_oversell.sh 'JKT-RAIN-M-BLU#001'`, then restore.
  - Result: exactly one dispute `JKT-RAIN-M-BLU#001|root` of kind `oversell` (titled "Sold twice" on the tablet) in `GET /api/exceptions?status=open`,
    with two branches (the pack, whose leaf is the tablet's sale, and HQ's sale), the same dispute on tablet A's
    Exceptions tab, and the exception count recorded. The words on stage are those of the ledger note (#63 read by the
    owner).
  - Who: agent: box+capella for the cluster; owner for the tablet and the stage.
  - Closes: #90, #65, #63.
- [ ] **8. One deliberate double-scan produces one exception, not a lost or duplicated unit.**
  - How: beat 5. Both tablets Take `JKT-RAIN-L-BLU#001` (untouched until now) out of range of each other, then rejoin.
  - Result: one "Scanned out twice" (kind `double_scan`) exception for that unit on each tablet and, once synced, on HQ; the conservation row
    for `JKT-RAIN-L-BLU` shows the unit as `disputed`, not in custody and not lost (`holds` true).
  - Who: owner.
  - Closes: #116, #98.

Cross-cutting setup, closed by the pre-flight passing live rather than by one line: #38, #39, #40, #41 (Capella),
#45, #48, #99 (box and Edge Server).
