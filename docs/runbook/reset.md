# Reset: back to "packed nothing yet"

Between rehearsals and before the real show. One script does the cloud and the box; the tablets are by hand.

```
scripts/demo/reset_rehearsal.sh --yes
```

Run it from the repository root on a machine with `.env` (the Capella SDK credential and `SIAB_TRIP`). Without
`--yes` it prints its usage, exits 2 and changes nothing. With it, in order:

1. `uv run python -m siab_capella reset-trip --trip $SIAB_TRIP --yes`: deletes the trip's `allocation`, `transaction`
   and `exception` documents in Capella (`docs/capella-setup.md`). App Services imports the deletes and routes the
   tombstones to the trip's channel, so they reach the box (verified by #41).
2. `uv run python -m siab_capella seed --yes`: puts `product`, `inventory` and `trip` back to the contract fixtures.
   Run `uv run python -m siab_capella seed --diff` first if anyone edited a seed document in Capella.
3. `curl -X POST $SIAB_BOX_STATUS_URL/bytes/reset` on the box agent (default `http://127.0.0.1:8787`): zeroes the
   byte counter.

`SIAB_TRIP` and `SIAB_BOX_STATUS_URL` are read from the environment, else from `.env`.

## Then, by hand

- **Restore the uplink** (`box/install/uplink.sh restore`) and keep the tablets on the box's LAN, so the deletes
  reach them.
- **Each tablet and the phone:** Diagnostics, **Rebuild derived state**, or reinstall the app. This re-reduces every
  movement; with the tombstones in, nothing is packed.
- **HQ screen:** reload. The conservation table shows no `in_custody`, `left_store` 0 and the indicator reads `HOLDS ·
  live`; the exceptions panel is empty. If it still shows a dispute, the HQ reconciler wrote it between the delete and
  your look: run `curl -X POST http://127.0.0.1:8788/api/reconcile/run` and look again.
- **Box:** nothing to restart.

## Check it worked (agent with `capella` and `box`)

Conservation shows nothing packed and `curl http://127.0.0.1:8787/status` shows `"in": 0, "out": 0` in `bytes`. This is
the verification plan's "reset really resets" line; it is filed as a `needs-verification` issue (see the PR).
