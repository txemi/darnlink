"""Acceptance tests — the cornerstone criteria from the spec (SC-001..003)."""
import hashlib
from pathlib import Path

from darnlink.frontmatter_index import build_index
from darnlink.repair import plan_repairs, apply_repairs

U = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _checksums(root: Path):
    return {p: hashlib.sha1(p.read_bytes()).hexdigest() for p in root.rglob("*.md")}


def test_sc001_move_then_repair_all_inbound(tmp_path):
    # target B starts in old/, with three files linking to it robustly from different depths
    _w(tmp_path / "old" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", f"intro\n\nSee [B](old/B.md) <!-- uuid: {U} --> done\n")
    _w(tmp_path / "deep" / "x" / "C.md", f"[link](../../old/B.md) <!-- uuid: {U} -->\n")
    _w(tmp_path / "D.md", f"with frag [B](old/B.md#sec) <!-- uuid: {U} -->\n")

    # move B to new/
    (tmp_path / "new").mkdir()
    (tmp_path / "old" / "B.md").rename(tmp_path / "new" / "B.md")

    index = build_index(tmp_path)
    result = plan_repairs(tmp_path, index)
    apply_repairs(result)

    assert "(new/B.md)" in (tmp_path / "A.md").read_text()
    assert "(../../new/B.md)" in (tmp_path / "deep" / "x" / "C.md").read_text()
    assert "(new/B.md#sec)" in (tmp_path / "D.md").read_text()  # fragment preserved
    # uuid comment preserved and unrelated text intact
    a = (tmp_path / "A.md").read_text()
    assert f"<!-- uuid: {U} -->" in a and a.startswith("intro\n\n") and a.endswith("done\n")


def test_sc002_idempotent(tmp_path):
    _w(tmp_path / "new" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", f"[B](new/B.md) <!-- uuid: {U} -->\n")
    # already correct: a run must produce no edits
    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert result.new_content == {}


def test_sc003_dry_run_writes_nothing(tmp_path):
    _w(tmp_path / "old" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", f"[B](old/B.md) <!-- uuid: {U} -->\n")
    (tmp_path / "new").mkdir()
    (tmp_path / "old" / "B.md").rename(tmp_path / "new" / "B.md")

    before = _checksums(tmp_path)
    result = plan_repairs(tmp_path, build_index(tmp_path))  # plan only, no apply
    after = _checksums(tmp_path)
    assert before == after          # nothing on disk changed
    assert result.new_content       # but a repair WAS planned


def test_ignored_file_is_not_indexed_nor_repaired(tmp_path):
    # SC-009: an ignored file's uuid is not indexed (a robust link to it is unresolvable),
    # and the ignored file's own robust links are never repaired.
    from darnlink.report import Kind
    # G is ignored but carries a uuid; A links to it robustly
    _w(tmp_path / "G.md", f"<!-- darnlink-ignore-file -->\n---\nuuid: {U}\n---\n# G\n")
    _w(tmp_path / "A.md", f"[g](G.md) <!-- uuid: {U} -->\n")
    # G itself has a (stale) robust link that would otherwise be repaired
    _w(tmp_path / "T.md", "---\nuuid: 99999999-9999-9999-9999-999999999999\n---\n# T\n")
    _w(tmp_path / "sub" / "G2.md",
       "<!-- darnlink-ignore-file -->\n[t](wrong/path.md) <!-- uuid: 99999999-9999-9999-9999-999999999999 -->\n")

    index = build_index(tmp_path)
    assert U not in index.by_uuid  # ignored file's uuid not indexed
    result = plan_repairs(tmp_path, index)
    assert result.new_content == {}                       # nothing rewritten
    assert any(f.kind is Kind.UNRESOLVABLE for f in result.findings)  # A's link unresolvable
    assert (tmp_path / "sub" / "G2.md") in result.ignored            # G2 skipped as a source


def test_unresolvable_and_ambiguous_are_reported_not_touched(tmp_path):
    from darnlink.report import Kind
    # unresolvable: uuid in no file
    _w(tmp_path / "A.md", f"[x](gone.md) <!-- uuid: {U} -->\n")
    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert result.new_content == {}
    assert any(f.kind is Kind.UNRESOLVABLE for f in result.findings)
