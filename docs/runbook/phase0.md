# Phase 0 runbook

The Phase 0 demo, run twice the same way. Every command below is copied from a merged README or port doc (cited per
step); every number only a live run can give is a placeholder that names the `needs-verification` issue that fills
it. This runbook has not yet been rehearsed (task 4 of WS7, #18, `[owner-present]`): until the rehearsal issue
(#124) records a run, treat each step as "as designed", not "as observed".

The acceptance checklist is [`phase0-acceptance.md`](phase0-acceptance.md); the labels and scripts are described in
[`scripts/demo/README.md`](../../scripts/demo/README.md); putting everything back between runs is
[`reset.md`](reset.md).

## The two setups (D7, #19)

The cable beats cut the box's uplink. There are two ways, and the **default** needs one laptop.

| | Default: one laptop | Alternative: two machines |
|---|---|---|
| Where the HQ screen runs | on the box laptop, beside `box/run.sh` | on a second machine with its own internet |
| The cut | `box/install/uplink.sh cut` (the agent refuses the replicator's connections) | pull the travel router's WAN cable |
| The plug-in | `box/install/uplink.sh restore` | put the WAN cable back |
| What HQ shows meanwhile | live: it has internet, Capella simply receives nothing from the box | live, same |
| The status page says | UPLINK CUT (software cut) | UPLINK CUT, "App Services unreachable", within 10 s (`box/README.md`, "Cutting the uplink") |
| Extra for the second machine | | `SIAB_BOX_STATUS_URL=http://<box>:8787` in its `.env`, so its HQ screen and `uplink.sh` reach the agent |

Each step that cuts says what to do in both. Say "cable" on stage in either case; the software cut is the same
event to the replicator (Edge Server cannot tell the two apart).

## Pre-flight

Do this the evening before, then again an hour before.

1. **Checkout and environment.** On the box laptop: `uv sync`; `.env` filled from `.env.example` (never committed).
   The Capella names and `SIAB_TRIP` are in [`../capella-setup.md`](../capella-setup.md), the `EDGE_*` and
   `SIAB_BOX_*` names in `box/README.md`.
2. **Capella is built and seeded**, once per cluster (`docs/capella-setup.md`, "The commands, in order"):
   ```
   uv run python -m siab_capella provision --yes
   uv run python -m siab_capella seed --yes
   uv run python -m siab_capella app-services apply --yes
   uv run python -m siab_capella app-services verify
   ```
   `verify` must exit 0. Read each plan (`--dry-run`) before the first `--yes`: the cluster is shared.
3. **Nothing packed yet.** Run [`reset.md`](reset.md) (`scripts/demo/reset_rehearsal.sh --yes`). This also zeroes the
   byte counter.
4. **Box up, in two terminals.** The laptop on the travel router's LAN (the router's own WPA2 network).
   `box/install/install.sh` once, then `box/run.sh --edge-only` in one terminal and `box/run.sh --agent-only` in the
   other (together they are `box/run.sh`; split, beat 3 can stop Edge Server alone, because the agent keeps the
   byte count and the software cut in memory and a restart zeroes them, `ports/box-agent.md`). First run: allow
   `couchbase-edge-server` and `python3` through the macOS firewall (`box/README.md`). Open `http://<box>:8787/`:
   Edge Server up, replication `idle`, uplink reachable, bytes `0`.
5. **HQ screen up.** `uv run python -m siab_hq serve` and open `http://127.0.0.1:8788/` (it listens on the
   presenter's machine only). The box panel needs `SIAB_BOX_STATUS_URL` in `.env`. The screen says `trip open: live
   view, nothing settled`; the conservation indicator reads `HOLDS · live` with nothing packed.
6. **Tablets paired.** Tablet A, tablet B and phone-1 on the router's LAN. On each: Diagnostics, "Pair with a box",
   scan the QR at `http://<box>:8787/pair/<device>` (`tablet-a`, `tablet-b`, `phone-1`). Diagnostics shows the box
   link and, on an Enterprise build, the mesh peers (`app/README.md`: device-to-device sync needs
   `SIAB_CBL_EDITION=enterprise`; a Community build shows `mesh: unavailable (Community Edition)` and beat 4 cannot
   be shown).
7. **Labels on the table.** `uv run python scripts/demo/labels.py --out labels.html`, printed at 100% scale. Keep
   the serials 001 and 002 of every SKU at hand for the pack; `JKT-RAIN-M-BLU#001` is the oversell unit and
   `JKT-RAIN-L-BLU#001` the double-scan unit.
8. **Byte counter at zero.** `curl -X POST http://127.0.0.1:8787/bytes/reset` (the reset script already did it; do
   it again if anything synced since).

Pre-flight closes the setup issues when it passes live: #38, #39, #40, #41 (Capella), #45, #48 (box), #99 (Edge
Server from the pairing payload).

## Beat 1: Pack

*Proves acceptance line 1 and, with the HQ screen, line 6.*

1. On tablet A open the Custody tab and select **Pack**. The header reads `PACKING store-richmond → box-07`.
2. Scan serials 001 and 002 of every SKU: 32 units. Each scan is accepted at once and appears in "This session".
3. On the HQ screen the conservation table drops each SKU's `store_on_hand` by two as the pack replicates, and
   `in_custody` shows `box-07: 2` per SKU. The indicator stays `HOLDS · live`.

Audience sees: store on-hand falling a scan at a time on the HQ half of the screen.

## Beat 2: Pull the cable and keep selling

*Proves acceptance line 2.*

1. The cut. **Default:** `box/install/uplink.sh cut`. **Alternative:** pull the router's WAN cable. The status page
   shows UPLINK CUT.
2. On tablet A: Custody, **Take**, scan `JKT-RAIN-M-BLU#001` and a few others (the header reads `TAKING FROM
   box-07`). Then Sell: scan a unit into the basket, tap **Cash** or **Card (simulated)**.
3. On tablet B sell a few units the same way.

Audience sees: sales going through with the status page showing the cut. The byte counter does not move.

## Beat 3: The box goes dark

*Proves acceptance line 3.*

1. Power the box off: Ctrl-C the `box/run.sh --edge-only` terminal (and unplug the router if you want it visible).
   The agent stays up, so the byte counter and the cut survive.
2. Tablet A sells a unit; tablet B's Shelf and Exceptions update through device-to-device sync (Diagnostics, mesh
   peers, shows the other tablet as last seen a moment ago).
3. Tablet B sells a different unit; tablet A's Shelf reflects it.
4. Start the box again: `box/run.sh --edge-only`. It resumes from its database; the tablets reconnect.

Audience sees: two tablets agreeing with nothing between them.

## Beat 4: The split

*Proves acceptance line 4, and line 6 while tablet B is out of range.*

1. Tablet B: Custody, **Take**, scan eight units off the box.
2. Tablet B leaves range (Wi-Fi off, or walk out of the venue's coverage). The box keeps selling on tablet A.
3. Tablet B sells three of the eight (Sell tab).
4. Tablet B comes back into range. Custody, **Return**, scan the five unsold units.
5. Check the box and tablet B agree without the cloud: the Shelf on tablet B and tablet A show the same `here` and
   `box` counts, and the uplink is still cut. On the HQ screen the conservation row indicator reads `HOLDS · live`
   (HQ's view lags by what the cable has kept back).

Audience sees: a tablet that walked off with eight jackets and was still a store.

## Beat 5: The double-scan

*Proves acceptance line 8.*

1. Put tablet A and tablet B out of range of each other (Wi-Fi off on one).
2. Both tablets: Custody, **Take**, scan `JKT-RAIN-L-BLU#001`. Each scan is accepted; neither tablet can know.
3. Bring them back in range. Each tablet's Exceptions tab shows one `double_scan` dispute for the unit, and it is the
   same dispute (`JKT-RAIN-L-BLU#001|<pack txn>`). The unit is counted nowhere: not lost, not twice.

Audience sees: one exception, not a duplicated unit.

## Conflict-free by construction

*Sixty to ninety seconds. The words below are copied into the Phase 0 runbook as they stand; change them here
first.*

**Before the beat.** The uplink is cut. One rain shell, packed onto the box before the cable came out, has been
sold on a tablet during the offline beats. On the HQ screen, the staged HQ sale of that same unit is ready in WS5's
stage control: the flagship's count-based till still believes it has the jacket. The HQ exception panel is not on
the projector yet.

**Do.**

1. Fire the staged HQ sale. Say: "Meanwhile, back at the flagship, someone just sold the same jacket."
2. Plug the cable in. Let the byte counter tick.
3. Open the exception on the HQ screen and show both branches: one is the pack onto box-07, whose chain ends in the
   tablet's sale; the other is HQ's sale.

**What the audience sees.** One `oversell` exception with two `branches`, side by side, and a proposed refund. On
the tablet, the jacket is `disputed`: counted neither on the Shelf nor as sold, and the same dispute is in the
tablet's exceptions. On the HQ screen, the conservation row for the rain shell still reads `holds`, with one unit
disputed.

**Say this.** "Two sales of the last unit are not a conflict. They are a fork in one unit's history, and the fork
is the exception, with both sales attached."

**If asked "where did the resolver run?"** "Nowhere. There isn't one. Every sale is a fact that is never edited,
so nothing ever conflicts. The tablet, and HQ, each run the same rules over the same facts and find the same fork;
each writes the same dispute under the same key. The box just carried the documents."

**If asked "what if the tablet is still out of range?"** "Then HQ finds it on its own. HQ already had the pack, and
its own sale forks with it, so the dispute is on this screen before the tablet comes back. The tablet keeps selling
everything else, and when it meets the box it finds the same fork and files the same dispute. Whichever side sees
it first, nobody waits for the other."

**Live, not settled.** What the HQ screen shows during the trip is live: HQ's reduced view of the movements it has
received so far, which a device that is out of range can still add to. A trip is settled only when HQ closes it
(decision [007](../decisions/007-hq-settles-tentative-until-close.md)), and closes arrive in Phase 2. So the
conservation row says `holds` for now, and the beat does not call the trip done.

HQ's reconciler may list the dispute before the cable goes in, because the pack reached Capella before the cable
came out. Keep the exception panel off the projector until step 3, or use it: "HQ found it from its side; the
venue is about to find the same fork from its side."

#### Run sheet for this beat

Not part of the copied text. Proves acceptance lines 7 and 5. Before the beat: on tablet A, Custody **Take** then Sell `JKT-RAIN-M-BLU#001` (so the
pack's chain ends in the tablet's sale). The uplink is still cut from beat 2.

- **Rehearsal decision on the HQ exception panel (#61): provisional.** The default is to keep the exception panel off
  the projector until step 3. HQ's reconciler runs every `SIAB_RECONCILE_INTERVAL_S` (3 s) and has the pack from
  before the cut, so the panel lists HQ's own copy of the dispute within seconds of step 1, before the cable goes
  in. Put the stage control and the conservation table on the projector, keep the exception panel off it (a second
  window, or scrolled out of view) and bring it up at step 3. If the rehearsal finds that unworkable, the fallback
  is the last paragraph above ("or use it"), spoken. Whichever the rehearsal picks, edit this bullet and send any
  change to the words above to the note as a `for-foreman` issue, so the two stay one text. Decided at: *the
  rehearsal (#124)*.
- **Step 1, fire the staged sale.** In the HQ stage control pick `JKT-RAIN-M-BLU#001`, or from a terminal:
  `scripts/demo/stage_oversell.sh 'JKT-RAIN-M-BLU#001'`. It prints the transaction id and the dispute to expect
  (`oversell`, `JKT-RAIN-M-BLU#001|root`).
- **Step 2, plug the cable in.** **Default:** `box/install/uplink.sh restore`. **Alternative:** put the router's WAN
  cable back. Edge Server resumes from its checkpoint; the status page byte counter ticks.
- **Step 3, show both branches.** On HQ: the exceptions panel, `oversell`, two branches. On tablet A: the Exceptions
  tab.
- **The byte number (acceptance line 5).** Read `bytes.out` and `bytes.in` from `http://<box>:8787/status` (or
  the box panel on the HQ screen) once the replication state is back to `idle`. The line is a day of fifty
  transactions: count the movements the HQ conservation view shows since the reset, and if it is under fifty, sell
  more before the plug-in. The number to beat is under 100 KB (`____` movements counted); the observed number is a placeholder filled by
  **#46** (replicate through the agent's proxy to live App Services): `____ B out, ____ B in`.

## After the show

`box/install/uplink.sh status` shows `"cut": false`. Leave the HQ screen up until the exception count and the
conservation screenshot are saved (acceptance lines 6 to 8). Then [`reset.md`](reset.md).
