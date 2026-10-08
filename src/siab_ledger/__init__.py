"""The custody ledger reducer, reference implementation (WS1). Interface: ``ports/ledger.md``.

Pure functions, no I/O: ``reduce`` turns the immutable ``transaction`` documents and HQ's resolutions into each unit's
holder, the counts and the forks; ``exceptions_for`` gives the ``exception`` documents a detector writes;
``conservation`` gives the per-SKU rows. ``hlc_now`` and ``hlc_receive`` are the hybrid logical clock.
"""

from .chain import Fork, LedgerState, Unit, reduce
from .conservation import Row, conservation
from .exceptions import exception_id, exceptions_for
from .hlc import Hlc, compare_hlc, format_hlc, hlc_now, hlc_receive, parse_hlc

__all__ = [
    "Fork",
    "Hlc",
    "LedgerState",
    "Row",
    "Unit",
    "compare_hlc",
    "conservation",
    "exception_id",
    "exceptions_for",
    "format_hlc",
    "hlc_now",
    "hlc_receive",
    "parse_hlc",
    "reduce",
]
