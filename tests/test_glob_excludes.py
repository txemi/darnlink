"""Feature 009: `--exclude` matches directory names by glob (fnmatch), backward-compatible.

Acceptance (specs/009-glob-excludes/spec.md): word-boundary `old` globs skip the family without
over-matching `folder`/`holder`; no-wildcard patterns still match exactly.
"""
from pathlib import Path

from darnlink.frontmatter_index import iter_markdown_files


def _tree(root: Path, *dirs: str) -> None:
    for d in dirs:
        p = root / d
        p.mkdir(parents=True, exist_ok=True)
        (p / "x.md").write_text("# x\n", encoding="utf-8")


def _dirs_scanned(root: Path, excludes) -> set[str]:
    # the parent directory name of every .md that survived the exclude
    return {p.parent.name for p in iter_markdown_files(root, set(excludes))}


def test_exact_pattern_no_wildcard_matches_exactly(tmp_path):
    _tree(tmp_path, "old", "folder", "bold", "old_html")
    got = _dirs_scanned(tmp_path, {"old"})
    assert "old" not in got                      # excluded
    assert {"folder", "bold", "old_html"} <= got  # NOT excluded (no substring match)


def test_prefix_glob(tmp_path):
    _tree(tmp_path, "old", "old_html", "old_impl", "holder")
    got = _dirs_scanned(tmp_path, {"old_*"})
    assert "old_html" not in got and "old_impl" not in got
    assert {"old", "holder"} <= got              # `old` (no underscore) and `holder` survive


def test_suffix_glob(tmp_path):
    _tree(tmp_path, "001_old", "folder", "cold")
    got = _dirs_scanned(tmp_path, {"*_old"})
    assert "001_old" not in got
    assert {"folder", "cold"} <= got             # `cold` has no `_old`, `folder` unaffected


def test_dot_suffix_glob(tmp_path):
    _tree(tmp_path, ".github.old", "keep")
    got = _dirs_scanned(tmp_path, {"*.old"})
    assert ".github.old" not in got
    assert "keep" in got


def test_old_family_together_no_over_match(tmp_path):
    _tree(tmp_path, "old", "old_html", "001_old", ".github.old", "old_implementation",
          "folder", "holder", "keep")
    got = _dirs_scanned(tmp_path, {"old", "old_*", "*_old", "*.old"})
    # whole 'old' family gone…
    for gone in ("old", "old_html", "001_old", ".github.old", "old_implementation"):
        assert gone not in got
    # …and nothing spurious
    assert {"folder", "holder", "keep"} <= got


def test_default_style_names_regression(tmp_path):
    _tree(tmp_path, "node_modules", "src")
    got = _dirs_scanned(tmp_path, {"node_modules"})
    assert "node_modules" not in got and "src" in got
