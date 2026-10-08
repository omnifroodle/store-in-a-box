"""scripts/check_links.py: relative links, GitHub blob links and path citations resolve in a checkout."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_checker():
    spec = importlib.util.spec_from_file_location("check_links", ROOT / "scripts" / "check_links.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


def run(capsys, *argv: str) -> tuple[int, list[str], list[str]]:
    code = load_checker().main(list(argv))
    out, err = capsys.readouterr()
    return code, out.splitlines(), err.splitlines()


def test_check_links_flags_missing_relative_target(tmp_path, capsys):
    repo = make_repo(tmp_path, {
        "README.md": "See [the spec](docs/SPEC.md) and\n[a note](docs/architecture/missing.md#section).\n",
        "docs/SPEC.md": "# Spec\n",
    })
    code, out, _ = run(capsys, "--root", str(repo))
    assert code == 1
    assert out == ["README.md:2: docs/architecture/missing.md#section"]


def test_check_links_passes_when_every_target_exists(tmp_path, capsys):
    repo = make_repo(tmp_path, {
        "README.md": "[spec](docs/SPEC.md) · [top](#top) · ![img](docs/images/a.png \"title\")\n",
        "docs/SPEC.md": "[overview](architecture/overview.md) and [up](../README.md)\n",
        "docs/architecture/overview.md": "[sibling](app.md)\n",
        "docs/architecture/app.md": "x\n",
        "docs/images/a.png": "",
    })
    code, out, _ = run(capsys, "--root", str(repo))
    assert (code, out) == (0, [])


def test_check_links_resolves_github_blob_link_to_checkout(tmp_path, capsys):
    repo = make_repo(tmp_path, {
        "site/index.html": (
            '<a href="https://github.com/acme/demo/blob/main/docs/architecture/overview.md">ok</a>\n'
            '<a href="https://github.com/acme/demo/blob/main/docs/architecture/gone.md#x">dead</a>\n'
            '<a href="https://github.com/acme/demo/tree/main/contracts/">dir</a>\n'
        ),
        "docs/architecture/overview.md": "x\n",
        "contracts/README.md": "x\n",
    })
    code, out, _ = run(capsys, "--root", str(repo), "site/index.html")
    assert code == 1
    assert out == ["site/index.html:2: https://github.com/acme/demo/blob/main/docs/architecture/gone.md#x"]


def test_other_absolute_urls_are_listed_not_fetched(tmp_path, capsys):
    repo = make_repo(tmp_path, {
        "site/index.html": '<link href="https://fonts.example.com/css">\n<a href="mailto:a@example.com">m</a>\n',
    })
    code, out, err = run(capsys, "--root", str(repo), "site/index.html")
    assert (code, out) == (0, [])
    assert err == [
        "not fetched: site/index.html:1: https://fonts.example.com/css",
        "not fetched: site/index.html:2: mailto:a@example.com",
    ]


def test_html_links_resolve_relative_to_the_page(tmp_path, capsys):
    repo = make_repo(tmp_path, {
        "site/index.html": '<link href="styles.css">\n<a href="deck/">deck</a>\n<!-- <a href="old.html"> -->\n',
        "site/styles.css": "",
    })
    code, out, _ = run(capsys, "--root", str(repo), "site/index.html")
    assert code == 1
    assert out == ["site/index.html:2: deck/"]


def test_code_blocks_and_inline_code_are_not_links(tmp_path, capsys):
    repo = make_repo(tmp_path, {
        "docs/a.md": (
            "```mermaid\nflowchart LR\n  A[\"x\"](missing.md)\n```\n"
            "Quoted: `[note](missing.md)`.\n"
            "~~~\n[also](missing.md)\n~~~\n"
        ),
    })
    code, out, _ = run(capsys, "--root", str(repo))
    assert (code, out) == (0, [])


def test_default_files_cover_readme_docs_and_site(tmp_path):
    repo = make_repo(tmp_path, {
        "README.md": "", "docs/SPEC.md": "", "docs/architecture/x.md": "", "site/index.html": "", "site/other.html": "",
        "notes.md": "",
    })
    names = [p.relative_to(repo).as_posix() for p in load_checker().default_files(repo)]
    assert names == ["README.md", "docs/SPEC.md", "docs/architecture/x.md", "site/index.html"]


def test_cite_flags_missing_path(tmp_path, capsys):
    repo = make_repo(tmp_path, {
        "docs/note.md": (
            "The rules are in `contracts/fixtures/README.md`.\n"
            "The reducer is `src/siab_ledger/` and the port is `ports/ledger.md`.\n"
        ),
        "contracts/fixtures/README.md": "x\n",
        "src/README.md": "x\n",
        "ports/README.md": "x\n",
    })
    code, out, _ = run(capsys, "--root", str(repo), "--cite", "docs/note.md")
    assert code == 1
    assert out == ["docs/note.md:2: src/siab_ledger/", "docs/note.md:2: ports/ledger.md"]


def test_cite_ignores_non_path_code_spans(tmp_path, capsys):
    repo = make_repo(tmp_path, {
        "docs/note.md": (
            "Fields `prev_txn` and `to_custodian`; channel `trip:<trip-id>`;\n"
            "id `exc::<detector>::<unit_id>::<hash8>`.\n"
            "A ratio `a/b`, a URL `https://example.com/x/y`, a key `JKT-RAIN-M-BLU#001|root`.\n"
            "Placeholders `contracts/fixtures/ledger/<scenario>.json` and `docs/{x}.md`.\n"
            "```\ncontracts/not/checked/in/a/fence.json\n```\n"
        ),
    })
    code, out, _ = run(capsys, "--root", str(repo), "--cite", "docs/note.md")
    assert (code, out) == (0, [])


def test_cite_checks_paths_inside_commands_and_globs(tmp_path, capsys):
    repo = make_repo(tmp_path, {
        "docs/note.md": (
            "Run `python scripts/check_links.py --cite docs/note.md`.\n"
            "Fixtures `contracts/fixtures/ledger/*.json`, line `docs/note.md:3`, and `scripts/gone.py`.\n"
        ),
        "scripts/check_links.py": "",
        "contracts/fixtures/ledger/a.json": "{}",
    })
    code, out, _ = run(capsys, "--root", str(repo), "--cite", "docs/note.md")
    assert code == 1
    assert out == ["docs/note.md:2: scripts/gone.py"]
