"""The ledger's command line.

``python -m siab_ledger check [--fixtures DIR] [--seed N]``: run the ledger golden fixtures. Prints ``PASS <name>`` or
``FAIL <name>: <first difference>`` per fixture; exits 1 on any failure.

``python -m siab_ledger report --sets DIR --out FILE``: the differential test's Python half. For every ``*.json``
differential set in ``DIR`` (``scripts/ledger_diff.py generate``), the fixture runner's result (``expected``'s shape
plus ``drops``), as one canonical JSON object keyed by file name.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .fixtures import canonical, check_all, default_fixtures_dir, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="siab-ledger", description="The custody ledger reducer (WS1).")
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check", help="run every fixture in contracts/fixtures/ledger/")
    chk.add_argument("--fixtures", type=Path, default=None, help="fixture directory (default: the repository's)")
    chk.add_argument("--seed", type=int, default=0, help="seed for the shuffled re-runs (default 0)")
    rep = sub.add_parser("report", help="the result for every differential set in a directory, as canonical JSON")
    rep.add_argument("--sets", type=Path, required=True, help="directory of <fixture>-<k>.json sets")
    rep.add_argument("--out", type=Path, required=True, help="the report file to write")
    args = parser.parse_args(argv)

    if args.command == "report":
        results = report(args.sets)
        if not results:
            print(f"FAIL no sets in {args.sets}")
            return 1
        args.out.write_text(canonical(results), encoding="ascii")
        print(f"wrote {len(results)} sets to {args.out}")
        return 0

    directory = args.fixtures if args.fixtures is not None else default_fixtures_dir()
    outcomes = check_all(directory, args.seed)
    if not outcomes:
        print(f"FAIL no fixtures in {directory}")
        return 1
    for outcome in outcomes:
        print(outcome.line)
    return 0 if all(o.difference is None for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
