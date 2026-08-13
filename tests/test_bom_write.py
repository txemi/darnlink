"""#68 — a UTF-8 BOM must survive a WRITE, on every path that writes.

`tests/test_bom.py` already covers the read side. That is why the defect lived: every BOM fixture
in this repo put the mark on a file that gets **read**, never on one that gets **rewritten**, so
the CI matrix — whose stated purpose is *"Windows-authored files (BOM, CRLF, path separators)"* —
could not see it. The fixtures below put the BOM where the writing happens.
"""
from pathlib import Path

from darnlink.frontmatter_index import build_index
from darnlink.repair import plan_repairs, apply_repairs
from darnlink.robustify import plan_robustify, apply_robustify

U = "11111111-2222-3333-4444-555555555555"
BOM = "﻿"


def _w(p: Path, text: str, bom: bool = False) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text((BOM if bom else "") + text, encoding="utf-8")


def _has_bom(p: Path) -> bool:
    return p.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_robustify_keeps_the_bom_of_the_rewritten_source(tmp_path):
    _w(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", "see [B](B.md)\n", bom=True)

    apply_robustify(plan_robustify(tmp_path))

    assert _has_bom(tmp_path / "A.md"), "the source lost its BOM"
    assert "<!-- uuid:" in (tmp_path / "A.md").read_text(encoding="utf-8-sig")


def test_robustify_keeps_the_bom_of_a_target_given_a_uuid(tmp_path):
    """The target is rewritten too — it receives the uuid — and it is a different write call."""
    _w(tmp_path / "B.md", "---\ntitle: B\n---\n# B\n", bom=True)      # frontmatter, no uuid
    _w(tmp_path / "A.md", "see [B](B.md)\n")

    apply_robustify(plan_robustify(tmp_path))

    assert _has_bom(tmp_path / "B.md"), "the target lost its BOM when it was given a uuid"


def test_create_frontmatter_keeps_the_bom(tmp_path):
    """A target with NO frontmatter gets a block prepended — the write most likely to eat a BOM."""
    _w(tmp_path / "B.md", "# B (no frontmatter)\n", bom=True)
    _w(tmp_path / "A.md", "see [B](B.md)\n")

    apply_robustify(plan_robustify(tmp_path, create_frontmatter=True))

    b = tmp_path / "B.md"
    assert _has_bom(b), "the target lost its BOM when frontmatter was created"
    assert b.read_text(encoding="utf-8-sig").startswith("---\nuuid: "), "the BOM displaced the block"


def test_repair_keeps_the_bom_of_the_rewritten_source(tmp_path):
    """The fourth write path, reached through a different module."""
    _w(tmp_path / "new" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", f"see [B](old/B.md) <!-- uuid: {U} -->\n", bom=True)

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))

    a = tmp_path / "A.md"
    assert _has_bom(a), "repair lost the BOM"
    assert "new/B.md" in a.read_text(encoding="utf-8-sig"), "repair did not move the link"


def test_a_file_without_a_bom_does_not_gain_one(tmp_path):
    """The mirror half: preserving must not mean inventing."""
    _w(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", "see [B](B.md)\n")

    apply_robustify(plan_robustify(tmp_path))

    assert not _has_bom(tmp_path / "A.md"), "a BOM was invented"


def test_a_created_readme_has_no_bom(tmp_path):
    """A file that did not exist has no BOM to preserve — and must not be given one."""
    _w(tmp_path / "A.md", f"---\nuuid: {U}\n---\n\nsee [d](sub/)\n")
    (tmp_path / "sub").mkdir()

    apply_robustify(plan_robustify(tmp_path, create_readme=True))

    readme = tmp_path / "sub" / "README.md"
    assert readme.exists() and not _has_bom(readme)
