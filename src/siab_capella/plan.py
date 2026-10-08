"""A plan is a list of steps: each says what it would change, and how. Every subcommand prints its plan first; only
`--yes` runs it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TextIO

from .gateway import ManualStepRequired

NO_CHANGE = ("unchanged", "exists")


@dataclass
class Step:
    action: str  # create, update, delete, ensure (offline: state unknown), refuse, or one of NO_CHANGE
    what: str
    run: Callable[[], object] | None = None
    detail: list[str] = field(default_factory=list)

    @property
    def change(self) -> bool:
        return self.action not in NO_CHANGE


def print_plan(title: str, steps: list[Step], out: TextIO, *, verbose: bool = False) -> int:
    """Print the plan (changes always, no-change steps with `verbose`); returns the number of changes."""
    changes = [s for s in steps if s.change]
    if steps and all(s.action == "ensure" for s in steps):
        print(f"{title}: {len(steps)} step(s) to ensure, current state unknown", file=out)
    else:
        print(f"{title}: {len(changes)} change(s), {len(steps) - len(changes)} already in place", file=out)
    for s in steps:
        if s.change or verbose:
            print(f"  {s.action:9} {s.what}", file=out)
            for d in s.detail:
                print(f"            {d}", file=out)
    return len(changes)


def run_plan(steps: list[Step], out: TextIO) -> list[str]:
    """Run every change in order. Steps the Management API cannot do are collected, not fatal: returns their manual
    instructions (empty when everything was applied)."""
    manual: list[str] = []
    for s in steps:
        if not s.change or s.run is None:
            continue
        try:
            s.run()
            print(f"  done      {s.what}", file=out)
        except ManualStepRequired as e:
            print(f"  manual    {s.what}", file=out)
            manual.extend(e.steps)
    return manual
