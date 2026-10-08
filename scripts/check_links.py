"""Check that the documentation's links and path citations resolve to files in this checkout.

Usage:
    python scripts/check_links.py [--root .] [FILE ...]
        FILE defaults to README.md, docs/**/*.md and site/index.html. Checks every relative link
        ([text](path), ![alt](path), [ref]: path, <a href="path">) and every
        https://github.com/<owner>/<repo>/blob|tree/<branch>/<path> link against the checkout. Anchors and query
        strings are ignored, and so are fenced code blocks (mermaid included), inline code and HTML comments.
        Other absolute URLs are listed on stderr, never fetched.
    python scripts/check_links.py [--root .] --cite FILE
        Every backticked token in FILE that looks like a repository path (it contains "/" and its first segment is
        one of the top-level directories in CITE_DIRS) must exist. Tokens with a placeholder (<id>, {x}) are skipped;
        a glob (*) must match at least one path.

Exit 0 when nothing is missing; otherwise one line per miss on stdout, "<file>:<line>: <target>", and exit 1.
Standard library only, no network.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

DEFAULT_FILES = ("README.md", "docs/**/*.md", "site/index.html")
CITE_DIRS = frozenset({"contracts", "docs", "src", "ports", "app", "scripts", "site", "sync", "box", "tests"})

_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_INLINE_CODE = re.compile(r"(`+)(.+?)\1")
_MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_MD_REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
_HTML_ATTR = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_GITHUB_FILE = re.compile(r"^https?://github\.com/[^/]+/[^/]+/(?:blob|tree)/[^/]+/(.+)$")
_PLACEHOLDER = re.compile(r"[<>{}]|\.\.\.|…")


def _blank_comments(text: str) -> str:
    """Replace HTML comments with spaces, keeping newlines so line numbers stay right."""
    return re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.DOTALL)


def _prose_lines(text: str, *, markdown: bool) -> Iterator[tuple[int, str]]:
    """(line number, line) outside fenced code blocks; in Markdown, inline code is blanked out."""
    in_fence: str | None = None
    for lineno, line in enumerate(_blank_comments(text).splitlines(), start=1):
        if markdown:
            fence = _FENCE.match(line)
            if fence:
                marker = fence.group(1)
                if in_fence is None:
                    in_fence = marker
                elif marker == in_fence:
                    in_fence = None
                continue
            if in_fence:
                continue
            line = _INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line)
        yield lineno, line


def links(text: str, *, markdown: bool) -> Iterator[tuple[int, str]]:
    """Every link target in the text, with its line number."""
    for lineno, line in _prose_lines(text, markdown=markdown):
        found: list[str] = []
        if markdown:
            found += _MD_LINK.findall(line)
            ref = _MD_REF_DEF.match(line)
            if ref:
                found.append(ref.group(1))
            found += _AUTOLINK.findall(line)
        found += _HTML_ATTR.findall(line)
        for target in found:
            yield lineno, target


def _exists(root: Path, rel: str) -> bool:
    rel = unquote(rel).strip()
    if not rel:
        return True
    if any(ch in rel for ch in "*?["):
        return any(root.glob(rel.lstrip("/")))
    return (root / rel.lstrip("/")).exists()


def check_file(path: Path, root: Path) -> tuple[list[str], list[str]]:
    """Return (misses, external URLs), each as "<file>:<line>: <target>"."""
    rel_name = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
    text = path.read_text(encoding="utf-8")
    markdown = path.suffix.lower() in {".md", ".markdown"}
    misses: list[str] = []
    external: list[str] = []
    for lineno, target in links(text, markdown=markdown):
        where = f"{rel_name}:{lineno}: {target}"
        github = _GITHUB_FILE.match(target)
        if github:
            repo_path = github.group(1).split("#", 1)[0].split("?", 1)[0]
            if not _exists(root, repo_path):
                misses.append(where)
            continue
        if _SCHEME.match(target) or target.startswith("//"):
            external.append(where)
            continue
        local = target.split("#", 1)[0].split("?", 1)[0]
        if not local:
            continue  # an anchor in the same file
        base = root if local.startswith("/") else path.parent
        if not (base / unquote(local).lstrip("/")).exists():
            misses.append(where)
    return misses, external


def code_spans(text: str) -> Iterator[tuple[int, str]]:
    """Every inline code span outside fenced blocks, with its line number."""
    in_fence: str | None = None
    for lineno, line in enumerate(text.splitlines(), start=1):
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if in_fence is None:
                in_fence = marker
            elif marker == in_fence:
                in_fence = None
            continue
        if in_fence:
            continue
        for match in _INLINE_CODE.finditer(line):
            yield lineno, match.group(2).strip()


def path_tokens(span: str) -> Iterator[str]:
    """The words of a code span that look like repository paths."""
    for word in span.split():
        word = word.strip("\"'(),;")
        word = re.sub(r":\d+(-\d+)?$", "", word)  # path:line
        word = word.split("#", 1)[0]
        if "/" not in word or _PLACEHOLDER.search(word) or _SCHEME.match(word):
            continue
        first = word.lstrip("./").split("/", 1)[0]
        if first in CITE_DIRS:
            yield word.lstrip("./") if word.startswith("./") else word


def check_cite(path: Path, root: Path) -> list[str]:
    rel_name = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
    misses = []
    for lineno, span in code_spans(path.read_text(encoding="utf-8")):
        for token in path_tokens(span):
            if not _exists(root, token):
                misses.append(f"{rel_name}:{lineno}: {token}")
    return misses


def default_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in DEFAULT_FILES:
        files += sorted(p for p in root.glob(pattern) if p.is_file())
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", default=".", help="repository root (default: the current directory)")
    parser.add_argument("--cite", metavar="FILE", help="check the backticked repository paths in FILE instead")
    parser.add_argument("files", nargs="*", metavar="FILE")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    def resolve(name: str) -> Path:
        p = Path(name)
        return (p if p.is_absolute() else root / p).resolve()

    if args.cite:
        misses = check_cite(resolve(args.cite), root)
    else:
        files = [resolve(f) for f in args.files] if args.files else default_files(root)
        misses = []
        for f in files:
            file_misses, external = check_file(f, root)
            misses += file_misses
            for line in external:
                print(f"not fetched: {line}", file=sys.stderr)
    for line in misses:
        print(line)
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
