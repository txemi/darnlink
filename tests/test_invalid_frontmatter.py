"""004: read uuid with the standard YAML parser; invalid frontmatter is reported, never accepted."""
from pathlib import Path

from darnlink.frontmatter_index import read_frontmatter_uuid, build_index
from darnlink.robustify import plan_robustify, apply_robustify
from darnlink.report import Kind

# `purpose: foo: bar` -> PyYAML "mapping values are not allowed here" (the real-world failure mode).
INVALID_FM = "---\nuuid: 11111111-1111-1111-1111-111111111111\npurpose: foo: bar\n---\n# X\n"
VALID_FM = "---\nuuid: 22222222-2222-2222-2222-222222222222\n---\n# Y\n"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_read_frontmatter_uuid_classifies():
    assert read_frontmatter_uuid("plain doc, no frontmatter\n") == ("none", None)
    assert read_frontmatter_uuid(VALID_FM) == ("valid", "22222222-2222-2222-2222-222222222222")
    assert read_frontmatter_uuid("---\ntitle: t\n---\n# z\n") == ("valid", None)
    status, u = read_frontmatter_uuid(INVALID_FM)
    assert status == "invalid" and u is None
    # uuid present but not a string scalar (list / number) -> malformed -> invalid (not str(...) garbage)
    assert read_frontmatter_uuid("---\nuuid:\n  - a\n  - b\n---\n# z\n") == ("invalid", None)
    assert read_frontmatter_uuid("---\nuuid: 12345\n---\n# z\n") == ("invalid", None)


def test_build_index_skips_and_records_invalid(tmp_path):
    _w(tmp_path / "B.md", INVALID_FM)
    _w(tmp_path / "C.md", VALID_FM)
    idx = build_index(tmp_path)
    assert "11111111-1111-1111-1111-111111111111" not in idx.by_uuid  # invalid never indexed
    assert "22222222-2222-2222-2222-222222222222" in idx.by_uuid
    assert (tmp_path / "B.md") in idx.invalid


def test_robustify_reports_invalid_target_and_does_not_touch_it(tmp_path):
    _w(tmp_path / "B.md", INVALID_FM)            # target with invalid YAML frontmatter
    _w(tmp_path / "A.md", "see [B](B.md)\n")
    result = plan_robustify(tmp_path, create_frontmatter=True)
    apply_robustify(result)
    assert (tmp_path / "B.md").read_text() == INVALID_FM         # never modified
    assert (tmp_path / "A.md").read_text() == "see [B](B.md)\n"  # link left plain (not anchored)
    assert any(f.kind is Kind.INVALID_FRONTMATTER for f in result.findings)
    assert (tmp_path / "B.md") in result.invalid


def test_valid_only_tree_has_no_unresolvable(tmp_path):
    # SC-013: robustify then repair on valid data -> every robustified link resolves.
    from darnlink.repair import plan_repairs
    _w(tmp_path / "B.md", VALID_FM)
    _w(tmp_path / "A.md", "see [B](B.md)\n")
    apply_robustify(plan_robustify(tmp_path))
    idx = build_index(tmp_path)
    rep = plan_repairs(tmp_path, idx)
    assert not any(f.kind is Kind.UNRESOLVABLE for f in rep.findings)
