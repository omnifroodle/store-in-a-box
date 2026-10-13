#!/usr/bin/env bash
# The ledger ports' differential test on a Mac (decision 010, WS10): generate the sets, the Python report, the Swift
# report (SIABCore's LedgerDifferentialTests, WS10b), and compare them set by set.
#
#   scripts/ledger_diff.sh [SEED]        (default: a random seed, printed so a failure can be re-run)
#
# Needs uv and Xcode. SIM_NAME picks the simulator (default "iPhone 16"). Exits non-zero on any difference.
set -euo pipefail

seed="${1:-$RANDOM}"
root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
cd "$root"

echo "ledger_diff: seed $seed, work in $work"
uv run python scripts/ledger_diff.py generate --seed "$seed" --out "$work/sets"
uv run python -m siab_ledger report --sets "$work/sets" --out "$work/python.json"
# TEST_RUNNER_-prefixed variables reach the test process on the simulator without the prefix.
TEST_RUNNER_SIAB_DIFF_SETS="$work/sets" TEST_RUNNER_SIAB_DIFF_OUT="$work/swift.json" \
  xcodebuild test -project app/StoreInABox.xcodeproj -scheme SIABCore \
    -destination "platform=iOS Simulator,name=${SIM_NAME:-iPhone 16}" \
    -only-testing:SIABCoreTests/LedgerDifferentialTests -quiet
uv run python scripts/ledger_diff.py compare "$work/python.json" "$work/swift.json"
