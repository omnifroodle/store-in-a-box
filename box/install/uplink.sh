#!/usr/bin/env bash
# The box's software uplink switch, over the box agent's API (bash and curl only).
# usage: box/install/uplink.sh {cut|restore|status|throttle}
# Talks to ${SIAB_BOX_STATUS_URL:-http://127.0.0.1:8787}, so it works from the HQ machine too.
# The physical cut needs no script: it is the travel router's WAN cable.
set -euo pipefail

url="${SIAB_BOX_STATUS_URL:-http://127.0.0.1:8787}"
url="${url%/}"

uplink_block() { # the {"uplink": {...}} part of a JSON body on stdin (the block has no nested objects)
  local block
  block="$(tr -d '\n' | grep -o '"uplink": *{[^}]*}')" || { echo "uplink.sh: no uplink block in the answer" >&2; exit 1; }
  echo "{${block}}"
}

case "${1:-}" in
  cut|restore)
    curl -fsS --max-time 5 -X POST "$url/uplink/$1" | uplink_block
    ;;
  status)
    curl -fsS --max-time 5 "$url/status" | uplink_block
    ;;
  throttle)
    echo "uplink.sh throttle: Phase 1 (showcase 9), not built yet" >&2
    exit 2
    ;;
  *)
    echo "usage: uplink.sh {cut|restore|status|throttle}" >&2
    exit 64
    ;;
esac
