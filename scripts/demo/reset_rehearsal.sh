#!/usr/bin/env bash
# Put the whole system back to "packed nothing yet" between rehearsals.
# usage: scripts/demo/reset_rehearsal.sh --yes
# Refuses (exit 2, writes nothing) without --yes. Run it from the repository root, on the machine that has .env.
#   1. siab-capella reset-trip: deletes the trip's allocations, transactions and exceptions in Capella
#   2. siab-capella seed: puts products, inventory and trips back to the contract fixtures
#   3. POST /bytes/reset on the box agent: zeroes the byte counter
# Then it prints the manual steps left on the tablets.
set -euo pipefail

if [[ "${1:-}" != "--yes" || $# -ne 1 ]]; then
  echo "usage: reset_rehearsal.sh --yes   (deletes the trip's custody history in Capella; see docs/runbook/reset.md)" >&2
  exit 2
fi

# .env is read the way the Python tools read it: the process environment wins. It is never sourced or printed.
dotenv() { [[ -f .env ]] && sed -n "s/^$1=//p" .env | tail -n 1 || true; }

trip="${SIAB_TRIP:-$(dotenv SIAB_TRIP)}"
box="${SIAB_BOX_STATUS_URL:-$(dotenv SIAB_BOX_STATUS_URL)}"
box="${box:-http://127.0.0.1:8787}"
box="${box%/}"
if [[ -z "$trip" ]]; then
  echo "reset_rehearsal.sh: SIAB_TRIP is not set (in .env or the environment)" >&2
  exit 1
fi

uv run python -m siab_capella reset-trip --trip "$trip" --yes
uv run python -m siab_capella seed --yes
curl -fsS --max-time 5 -X POST "$box/bytes/reset"
echo

cat <<'EOF'

Done in Capella and on the box. Still to do by hand:
  - each tablet and the phone: Diagnostics -> Rebuild derived state (or reinstall the app). The tombstones reach a
    device only when it is on the box's LAN with the uplink restored, so do this after `box/install/uplink.sh restore`.
  - HQ screen: reload it; the conservation table should show nothing packed.
  - the box: nothing to restart (Edge Server resumes from its checkpoint; the byte counter is already zero).
EOF
