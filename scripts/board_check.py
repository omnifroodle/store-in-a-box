"""Foreman housekeeping: find where the issue board has fallen behind the code.

Usage: python3 scripts/board_check.py [owner/repo]
       python3 scripts/board_check.py --self-test

Counts as problems: closed workstream issues with unticked exit criteria, merged PRs whose `Closes` issue is still
open, open for-foreman notes, merged PRs with comments posted after the merge that the foreman has not acknowledged (a
later comment containing `[foreman: seen]`), open PRs that edit files outside their blueprint's Files list, worktrees
and local branches left behind after a merge, and the local default branch being behind origin.
Lists as information: open `needs-verification` issues per milestone (a milestone with one open cannot be tagged), open
PRs over the size cap (code lines only: tests and fixtures are not counted), worktrees with no PR, open `blog-worthy`
issues and draft posts waiting (set DRAFTS_DIR below).
Exits 1 when something needs attention. Needs only the standard library and `gh`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

GH = shutil.which("gh") or "/opt/homebrew/bin/gh"
DRAFTS_DIR = None  # e.g. Path("blog/content/posts"); posts without `draft: false` are listed as waiting
BLUEPRINTS_DIR = Path("docs/workstreams")
MAX_PR_LINES = 1500  # code lines (additions + deletions) above which a blueprint should have been split (FOREMAN.md)
TEST_DIRS = {"tests", "test", "__tests__"}  # any directory with one of these names, at any depth, is always allowed
FIXTURE_DIRS = {"fixtures", "testdata", "golden", "goldens", "snapshots", "__snapshots__"}
FIXTURE_GLOBS = ("*golden*", "*.snap", "*.lock", "*-lock.json")  # file names not counted against the size cap
LATE_COMMENT_PRS = 50  # how many recently merged PRs to scan for comments posted after the merge
SEEN_MARKER = "[foreman: seen]"  # a comment containing this acknowledges every late comment before it


# ---------------------------------------------------------------- pure helpers (covered by --self-test)

def is_test_path(path: str) -> bool:
    """True for a file under any test directory, top-level or nested (`tests/x.py`, `web/tests/x.mjs`)."""
    return any(part in TEST_DIRS for part in PurePosixPath(path).parts[:-1])


def is_non_code(path: str) -> bool:
    """Tests, fixtures and golden files: excluded from the PR size cap."""
    p = PurePosixPath(path)
    return (is_test_path(path)
            or any(part in FIXTURE_DIRS for part in p.parts[:-1])
            or any(fnmatch(p.name, g) for g in FIXTURE_GLOBS))


def code_lines(files: list[dict]) -> int:
    """Additions plus deletions over the files that are code (see is_non_code)."""
    return sum(f.get("additions", 0) + f.get("deletions", 0) for f in files if not is_non_code(f["path"]))


_BARE_FILE = re.compile(r"^[\w.-]+\.[A-Za-z0-9]+$")


def blueprint_files(text: str) -> list[str] | None:
    """Paths (in backticks) under a blueprint's `## Files` heading; None if it has no such section.

    A bare file name (no slash) that follows a full path in the same bullet is read as a sibling of that path, so
    "`a/b/one.yaml`, `two.yaml`" allows `a/b/one.yaml` and `a/b/two.yaml`. The bare name is also kept as a
    root-level path.
    """
    m = re.search(r"^## Files[^\n]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return None
    out: list[str] = []
    base: str | None = None
    for line in m.group(1).splitlines():
        if re.match(r"\s*[-*+] ", line) or not line.strip():
            base = None  # a new bullet (or a blank line) starts a new run
        for token in re.findall(r"`([^`\s]+)`", line):
            path = token.rstrip("/")
            if "/" in token:
                out.append(path)
                base = path if token.endswith("/") else str(PurePosixPath(path).parent)
            else:
                out.append(path)
                if base and _BARE_FILE.match(token):
                    out.append(f"{base}/{token}")
    return out


def outside(changed: list[str], allowed: list[str]) -> list[str]:
    """The changed paths that are not under (or matched by) any allowed path, and are not tests."""
    return [c for c in changed
            if not is_test_path(c)
            and not any(c == a or c.startswith(a + "/") or fnmatch(c, a) for a in allowed)]


def _ts(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def late_comments(pr: dict) -> list[dict]:
    """Comments posted after the PR merged and not yet acknowledged by a later `[foreman: seen]` comment.

    Nothing notifies the foreman of a comment on a merged PR, so these are easy to miss. A comment carrying the
    marker is the foreman's acknowledgement and clears every late comment before it.
    """
    merged = pr.get("mergedAt")
    if not merged:
        return []
    out: list[dict] = []
    for c in sorted(pr.get("comments") or [], key=lambda c: _ts(c["createdAt"])):
        if _ts(c["createdAt"]) <= _ts(merged):
            continue
        if SEEN_MARKER in (c.get("body") or ""):
            out = []
        else:
            out.append(c)
    return out


def blueprint_for(branch: str, root: Path = BLUEPRINTS_DIR) -> Path | None:
    m = re.match(r"ws(\d+)\w*/", branch)
    found = sorted(root.glob(f"WS{m.group(1)}-*.md")) if m else []
    return found[0] if found else None


# ---------------------------------------------------------------- gh and git

def run(*args: str) -> str:
    return subprocess.run(list(args), capture_output=True, text=True, check=False).stdout.strip()


def gh(*args: str) -> list:
    return json.loads(run(GH, *args) or "[]")


def default_branch(repo: str) -> str:
    return run(GH, "repo", "view", repo, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name") or "main"


def worktrees() -> dict[str, str]:
    """Branch -> path for every linked worktree (the main checkout is skipped)."""
    out: dict[str, str] = {}
    blocks = run("git", "worktree", "list", "--porcelain").split("\n\n")
    for block in blocks[1:]:
        lines = block.splitlines()
        path = next((x[len("worktree "):] for x in lines if x.startswith("worktree ")), "")
        for x in lines:
            if x.startswith("branch refs/heads/"):
                out[x[len("branch refs/heads/"):]] = path
    return out


def draft_posts() -> list[str]:
    if DRAFTS_DIR is None or not Path(DRAFTS_DIR).is_dir():
        return []
    out = []
    for path in sorted(Path(DRAFTS_DIR).glob("*.md")):
        head = path.read_text(encoding="utf-8").split("---")[1:2]
        front = head[0] if head else ""
        if not re.search(r"^draft:\s*false\s*$", front, re.MULTILINE):
            m = re.search(r"^title:\s*(.+)$", front, re.MULTILINE)
            out.append((m.group(1).strip().strip('"') if m else path.stem)[:70])
    return out


def has_label(issue: dict, name: str) -> bool:
    return any(label["name"] == name for label in issue["labels"])


# ---------------------------------------------------------------- the check

def check(repo: str) -> int:
    issues = gh("issue", "list", "--repo", repo, "--state", "all", "--limit", "300",
                "--json", "number,title,state,body,labels,milestone")
    prs = gh("pr", "list", "--repo", repo, "--state", "merged", "--limit", "200",
             "--json", "number,body,headRefName")
    open_prs = gh("pr", "list", "--repo", repo, "--state", "open", "--limit", "50",
                  "--json", "number,headRefName,files")
    by_num = {i["number"]: i for i in issues}
    problems = 0

    for i in issues:
        is_ws = re.match(r"WS\d+\w*:", i["title"]) and any(l["name"].startswith("ws:") for l in i["labels"])
        if is_ws and i["state"] == "CLOSED":
            left = len(re.findall(r"- \[ \]", i["body"] or ""))
            if left:
                problems += 1
                print(f"closed #{i['number']} {i['title'][:50]}: {left} exit criteria still unticked")

    for p in prs:
        for n in re.findall(r"Closes\s+#(\d+)", p["body"] or ""):
            issue = by_num.get(int(n))
            if issue and issue["state"] == "OPEN":
                problems += 1
                print(f"PR #{p['number']} says Closes #{n} but the issue is still open")

    recent = gh("pr", "list", "--repo", repo, "--state", "merged", "--limit", str(LATE_COMMENT_PRS),
                "--json", "number,title,mergedAt,comments")
    for p in recent:
        late = late_comments(p)
        if late:
            problems += 1
            who = ", ".join(sorted({(c.get("author") or {}).get("login") or "?" for c in late}))
            print(f"merged PR #{p['number']} {p['title'][:40]}: {len(late)} comment(s) after the merge ({who}); "
                  f"read, act, then reply with {SEEN_MARKER}")

    for i in issues:
        if i["state"] == "OPEN" and has_label(i, "for-foreman"):
            problems += 1
            print(f"inbox: #{i['number']} {i['title'][:60]}")

    debt: dict[str, list[dict]] = {}
    for i in issues:
        if i["state"] == "OPEN" and has_label(i, "needs-verification"):
            debt.setdefault((i.get("milestone") or {}).get("title") or "no milestone", []).append(i)
    for name, items in sorted(debt.items()):
        for i in items:
            print(f"needs-verification [{name}]: #{i['number']} {i['title'][:60]}")
        print(f"{name} cannot be tagged: {len(items)} open needs-verification issue(s) (info)")

    for p in open_prs:
        files = p.get("files") or []
        size = code_lines(files)
        if size > MAX_PR_LINES:
            print(f"PR #{p['number']} is {size} code lines (over {MAX_PR_LINES}, tests and fixtures not counted): "
                  "should have been split (info)")
        spec = blueprint_for(p["headRefName"])
        allowed = blueprint_files(spec.read_text(encoding="utf-8")) if spec else None
        if allowed is None:
            continue  # no blueprint, or an older spec without a Files section
        stray = outside([f["path"] for f in files], allowed)
        if stray:
            problems += 1
            shown = ", ".join(stray[:6]) + (" ..." if len(stray) > 6 else "")
            print(f"PR #{p['number']} edits {len(stray)} file(s) outside {spec.name} Files: {shown}")

    for i in issues:
        if i["state"] == "OPEN" and has_label(i, "blog-worthy"):
            print(f"blog-worthy: #{i['number']} {i['title'][:60]} (info)")
    for name in draft_posts():
        print(f"draft waiting: {name} (info)")

    branch = default_branch(repo)
    merged_heads = {p["headRefName"] for p in prs}
    open_heads = {p["headRefName"] for p in open_prs}
    trees = worktrees()
    for head, path in sorted(trees.items()):
        if head in merged_heads:
            problems += 1
            print(f"stale worktree (PR merged): {path} [{head}]")
        elif head not in open_heads:
            print(f"worktree with no PR (in flight or abandoned?): {path} [{head}] (info)")
    local = run("git", "for-each-ref", "--format=%(refname:short)", "refs/heads").split()
    gone = [b for b in local if b not in trees and b != branch and b in merged_heads]
    if gone:
        problems += 1
        print(f"{len(gone)} local branch(es) left after merge: {' '.join(gone)}")

    subprocess.run(["git", "fetch", "-q", "origin", branch], check=False)
    behind = run("git", "rev-list", "--count", f"HEAD..origin/{branch}")
    if behind not in ("", "0"):
        problems += 1
        print(f"local checkout is {behind} commit(s) behind origin/{branch}")

    print("board matches code" if not problems else f"{problems} item(s) need attention")
    return 1 if problems else 0


# ---------------------------------------------------------------- self-test

def self_test() -> int:
    spec = """# WS7: example

## Scope
Not a file list: `src/elsewhere.py` here is ignored.

## Files
Owned:
- `src/area/` (new)
- `config/places/home.yaml`, `office.yaml`, `garden.yaml` (the `items:` block only)
- `src/neighbour/models.py`: add `Thing.field` and `notes.md`
- `README.md`
- `tests/` (always allowed)

## Interfaces
- `src/other.py`
"""
    allowed = blueprint_files(spec)
    assert allowed is not None
    assert "src/area" in allowed and "README.md" in allowed
    assert "src/elsewhere.py" not in allowed and "src/other.py" not in allowed
    changed = [
        "src/area/new.py",                 # owned directory
        "config/places/home.yaml",         # full path
        "config/places/office.yaml",       # bare name after a full path (the bug this fixes)
        "config/places/garden.yaml",
        "src/neighbour/models.py",
        "README.md",
        "tests/test_area.py",              # top-level tests
        "web/tests/area.test.mjs",         # nested tests
        "src/neighbour/routes.py",         # NOT listed
        "config/other/office.yaml",        # bare name only resolves against its own bullet's path
        "src/elsewhere.py",                # mentioned outside the Files section
    ]
    assert outside(changed, allowed) == ["src/neighbour/routes.py", "config/other/office.yaml", "src/elsewhere.py"], \
        outside(changed, allowed)
    assert blueprint_files("# WS1\n\n## Scope\nx\n") is None

    assert is_test_path("tests/a.py") and is_test_path("viewer/tests/a.mjs") and is_test_path("a/b/__tests__/c.ts")
    assert not is_test_path("src/tests.py") and not is_test_path("tests")
    files = [
        {"path": "src/a.py", "additions": 900, "deletions": 100},
        {"path": "tests/test_a.py", "additions": 800, "deletions": 0},
        {"path": "viewer/tests/a.test.mjs", "additions": 300, "deletions": 0},
        {"path": "tests/fixtures/golden_run.json", "additions": 2000, "deletions": 1500},
        {"path": "data/golden/report.json", "additions": 400, "deletions": 0},
        {"path": "pkg/fixtures/sample.yaml", "additions": 50, "deletions": 0},
        {"path": "web/app.js", "additions": 200, "deletions": 50},
    ]
    assert code_lines(files) == 1250, code_lines(files)

    assert blueprint_for("feature/x") is None

    def c(at: str, body: str = "note", login: str = "someone") -> dict:
        return {"createdAt": at, "body": body, "author": {"login": login}}
    merged = "2026-01-10T12:00:00Z"
    assert late_comments({"mergedAt": None, "comments": [c("2026-01-11T00:00:00Z")]}) == []  # not merged
    assert late_comments({"mergedAt": merged, "comments": []}) == []
    before = c("2026-01-10T11:59:59Z", "Review gate: PASS")
    after = c("2026-01-10T12:00:01Z", "this broke on the device")
    assert late_comments({"mergedAt": merged, "comments": [before]}) == []  # comments before the merge are fine
    assert late_comments({"mergedAt": merged, "comments": [after, before]}) == [after]  # order-independent
    seen = c("2026-01-10T13:00:00Z", "Filed #12. [foreman: seen]", "foreman")
    assert late_comments({"mergedAt": merged, "comments": [before, after, seen]}) == []  # acknowledged
    later = c("2026-01-11T09:00:00+00:00", "one more thing")  # offset form parses too
    assert late_comments({"mergedAt": merged, "comments": [after, seen, later]}) == [later]  # only after the ack
    print("self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find where the issue board has fallen behind the code (see FOREMAN.md, loop step 0c).")
    parser.add_argument("repo", nargs="?", help="owner/repo (default: the repo of the current directory)")
    parser.add_argument("--self-test", action="store_true", help="check the pure helpers and exit (no gh, no git)")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    repo = args.repo or run(GH, "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    return check(repo)


if __name__ == "__main__":
    raise SystemExit(main())
