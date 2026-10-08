#!/usr/bin/env bash
# Start the box in the foreground: Couchbase Edge Server and the box agent, both logged to box/logs/.
# One Ctrl-C stops both. Exits non-zero if either dies in its first 5 s, or later.
# usage: box/run.sh [--edge-only|--agent-only]
# Written for the bash 3.2 that macOS ships.
set -euo pipefail

box="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$box")"
edge_dir="$box/.edge-server"
logs="$box/logs"

mode=both
case "${1:-}" in
  "") ;;
  --edge-only) mode=edge ;;
  --agent-only) mode=agent ;;
  *) echo "usage: box/run.sh [--edge-only|--agent-only]" >&2; exit 64 ;;
esac

# Keep the laptop awake for the whole demo (re-runs this script under caffeinate once).
if [[ "$(uname -s)" == Darwin && -z "${SIAB_CAFFEINATED:-}" ]] && command -v caffeinate >/dev/null 2>&1; then
  SIAB_CAFFEINATED=1 exec caffeinate -i "$0" ${1+"$@"}
fi

if [[ -f "$repo/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "$repo/.env"
  set +a
fi

if [[ -x "$repo/.venv/bin/python" ]]; then
  py=("$repo/.venv/bin/python")
else
  py=(uv run --project "$repo" python)
fi
edge_bin="$edge_dir/couchbase-edge-server"

if [[ "$mode" != agent ]]; then
  [[ -x "$edge_bin" ]] || { echo "run.sh: no Edge Server; run box/install/install.sh first" >&2; exit 1; }
  if [[ ! -f "$edge_dir/config.json" ]]; then
    (cd "$repo" && "${py[@]}" -m siab_box render-config --out "$edge_dir/config.json")
  fi
  if [[ "${EDGE_TLS:-off}" == on && ! -f "$edge_dir/cert.pem" ]]; then
    ip="$(cd "$repo" && "${py[@]}" -c 'from siab_box.agent import lan_ip; print(lan_ip())')"
    "$edge_bin" --create-cert "CN=$ip" "$edge_dir/cert.pem" "$edge_dir/key.pem"
  fi
fi

mkdir -p "$logs"
stamp="$(date +%Y%m%d-%H%M%S)"
names=()
pids=()
log_files=()

start() { # name command...
  local name="$1" log="$logs/$1-$stamp.log"
  shift
  "$@" >>"$log" 2>&1 &
  names+=("$name")
  pids+=("$!")
  log_files+=("$log")
  echo "run.sh: started $name (pid $!), log $log"
}

# shellcheck disable=SC2329 # invoked by the traps below
stop_all() {
  trap - INT TERM EXIT
  local pid
  for pid in ${pids[@]+"${pids[@]}"} ${tail_pid:-}; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap 'stop_all; exit 130' INT TERM
trap stop_all EXIT

if [[ "$mode" != agent ]]; then
  (cd "$edge_dir" && exec "$edge_bin" "$edge_dir/config.json") >>"$logs/edge-server-$stamp.log" 2>&1 &
  names+=(edge-server); pids+=("$!"); log_files+=("$logs/edge-server-$stamp.log")
  echo "run.sh: started edge-server (pid $!), log $logs/edge-server-$stamp.log"
fi
if [[ "$mode" != edge ]]; then
  start agent "${py[@]}" -m siab_box agent
fi

tail -n +1 -F "${log_files[@]}" &
tail_pid=$!

dead() { # prints the name of the first process that has exited, if any
  local i
  for i in "${!pids[@]}"; do
    if ! kill -0 "${pids[$i]}" 2>/dev/null; then echo "${names[$i]}"; return 0; fi
  done
  return 1
}

sleep 5
if which="$(dead)"; then
  echo "run.sh: $which exited within 5 s; see box/logs/" >&2
  exit 1
fi
echo "run.sh: running. Status page: http://127.0.0.1:${SIAB_BOX_PORT:-8787}/ . Ctrl-C stops everything."
while ! which="$(dead)"; do
  sleep 1
done
echo "run.sh: $which exited; stopping the rest" >&2
exit 1
