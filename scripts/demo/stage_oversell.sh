#!/usr/bin/env bash
# Fire the staged HQ sale of a unit the box holds (the oversell beat).
# usage: scripts/demo/stage_oversell.sh <unit-id>      e.g. JKT-RAIN-M-BLU#001
# Talks to the HQ app at http://127.0.0.1:${SIAB_HQ_PORT:-8788} (ports/hq.md, POST /api/stage/hq-sale). The unit must be
# one HQ shows as held by the trip's box or a device: GET /api/stage/units lists them.
set -euo pipefail

unit="${1:-}"
if [[ ! "$unit" =~ ^[A-Z0-9]+(-[A-Z0-9]+)*#[0-9]{3}$ ]]; then
  echo "usage: stage_oversell.sh <unit-id>   (a unit id looks like JKT-RAIN-M-BLU#001)" >&2
  exit 64
fi

port="${SIAB_HQ_PORT:-8788}"
url="http://127.0.0.1:${port}"

# The unit id has only [A-Z0-9#-], so it needs no JSON escaping. The trip is the one HQ serves.
answer="$(curl -sS --max-time 10 -X POST -H 'Content-Type: application/json' \
  -d "{\"unit_id\": \"${unit}\"}" -w '\n%{http_code}' "$url/api/stage/hq-sale")" || {
  echo "stage_oversell.sh: the HQ app does not answer on port ${port} (python -m siab_hq serve)" >&2
  exit 1
}
status="${answer##*$'\n'}"
body="${answer%$'\n'*}"
if [[ "$status" != 200 ]]; then
  echo "stage_oversell.sh: HQ refused (${status}): ${body}" >&2
  exit 1
fi

# `|| true`: an answer without an "id" must reach the fallback message below, not kill the script under pipefail.
txn="$(printf '%s' "$body" | grep -o '"id": *"[^"]*"' | head -n 1 | sed 's/.*: *"\(.*\)"/\1/' || true)"
echo "staged HQ sale: ${txn:-<no id in the answer>}"
echo "expect one dispute within a reconcile interval (SIAB_RECONCILE_INTERVAL_S, default 3 s):"
echo "  kind oversell, unit ${unit}, dispute_key ${unit}|root, detector hq"
echo "  two branches: the pack onto the box (leaf: the tablet's sale, once it has synced), and HQ's sale ${txn}"
