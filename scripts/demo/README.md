# Demo scripts

Run from the repository root after `uv sync`. The runbook that uses them is `docs/runbook/phase0.md`.

| Script | What |
|---|---|
| `labels.py` | `uv run python scripts/demo/labels.py [--seed contracts/fixtures/seed/products.json] [--per-sku N] [--out labels.html]`: one label per unit `<SKU>#<serial>`, serials `001..N` (default 5 per SKU, decision D3), each with the SKU, serial, product name and a QR of exactly the text the tablet's scanner parses. Open the HTML in a browser and print at 100% scale on 30-up Avery 5160-style sheets (2 5/8 x 1 in). |
| `reset_rehearsal.sh` | `scripts/demo/reset_rehearsal.sh --yes`: `siab_capella reset-trip` and `seed`, then zero the box's byte counter, then print the manual tablet steps. Exits 2 and writes nothing without `--yes`. See `docs/runbook/reset.md`. |
| `stage_oversell.sh` | `scripts/demo/stage_oversell.sh <unit-id>`: `POST /api/stage/hq-sale` on the HQ app (`SIAB_HQ_PORT`, default 8788) and print the transaction id and the dispute to expect. |

`shellcheck scripts/demo/*.sh` is clean; the tests are in `tests/demo/`.
