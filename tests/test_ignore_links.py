"""Feature 006 — `<!-- darnlink-ignore-links -->`: source-only opt-out.

The file's OWN links are never touched (never robustified, never repaired), but it stays a
first-class TARGET: its uuid is indexed, so inbound robust links keep resolving and get repaired
when it moves. That last part is the whole difference from 003's `darnlink-ignore-file`, which
also drops the file from the index (FR-019).
"""
from pathlib import Path

from darnlink.frontmatter_index import build_index
from darnlink.links import find_robust_links
from darnlink.report import Kind
from darnlink.repair import plan_repairs, apply_repairs
from darnlink.robustify import plan_robustify, apply_robustify

U_IDX = "aaaaaaaa-1111-2222-3333-444444444444"   # the marked file's own uuid (it is a target)
U_B = "bbbbbbbb-1111-2222-3333-444444444444"     # a target the marked file links to
MARK = "<!-- darnlink-ignore-links -->"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_marked_file_keeps_its_plain_links_plain(tmp_path):
    # Acceptance 1: the motivating case — a generator rewrites INDEX.md, so anchoring it is churn.
    _w(tmp_path / "B.md", f"---\nuuid: {U_B}\n---\n# B\n")
    index_md = f"---\nuuid: {U_IDX}\n---\n{MARK}\n\n- [B](B.md)\n"
    _w(tmp_path / "INDEX.md", index_md)

    result = plan_robustify(tmp_path)
    apply_robustify(result)

    assert (tmp_path / "INDEX.md").read_text() == index_md  # byte-for-byte intact
    # FR-038: reported, never silent — and NOT as an actionable robustify finding.
    kinds = [f.kind for f in result.findings if f.file == (tmp_path / "INDEX.md")]
    assert Kind.IGNORED_LINKS in kinds
    assert Kind.ROBUSTIFY not in kinds


def test_marked_file_is_still_an_indexed_target(tmp_path):
    # FR-034 / Acceptance 2: this is exactly what darnlink-ignore-file makes impossible (FR-019).
    _w(tmp_path / "INDEX.md", f"---\nuuid: {U_IDX}\n---\n{MARK}\n# Index\n")
    index = build_index(tmp_path)
    assert U_IDX in index.by_uuid  # the marker must NOT hide it from the index


def test_inbound_robust_link_is_repaired_when_marked_file_moves(tmp_path):
    # Acceptance 2 end-to-end: others anchor to it, and their links heal when it moves.
    (tmp_path / "old").mkdir()
    _w(tmp_path / "old" / "INDEX.md", f"---\nuuid: {U_IDX}\n---\n{MARK}\n# Index\n")
    _w(tmp_path / "A.md", f"See [the index](old/INDEX.md) <!-- uuid: {U_IDX} -->\n")

    (tmp_path / "new").mkdir()
    (tmp_path / "old" / "INDEX.md").rename(tmp_path / "new" / "INDEX.md")

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))
    assert "(new/INDEX.md)" in (tmp_path / "A.md").read_text()


def test_marked_file_own_robust_links_are_not_repaired(tmp_path):
    # FR-033 / Acceptance 3: the generator re-emits the right path; darnlink must not fight it.
    (tmp_path / "old").mkdir()
    _w(tmp_path / "old" / "B.md", f"---\nuuid: {U_B}\n---\n# B\n")
    index_md = f"---\nuuid: {U_IDX}\n---\n{MARK}\n\n- [B](old/B.md) <!-- uuid: {U_B} -->\n"
    _w(tmp_path / "INDEX.md", index_md)

    (tmp_path / "new").mkdir()
    (tmp_path / "old" / "B.md").rename(tmp_path / "new" / "B.md")

    result = plan_repairs(tmp_path, build_index(tmp_path))
    apply_repairs(result)

    assert (tmp_path / "INDEX.md").read_text() == index_md  # stale path left alone, on purpose
    assert Kind.IGNORED_LINKS in [f.kind for f in result.findings if f.file == (tmp_path / "INDEX.md")]


def test_marker_inside_a_code_block_does_not_opt_out(tmp_path):
    # FR-036 / Acceptance 4: docs showing the marker must not self-opt-out (composes with 002).
    _w(tmp_path / "B.md", f"---\nuuid: {U_B}\n---\n# B\n")
    _w(tmp_path / "DOC.md", f"Use it like this:\n\n```markdown\n{MARK}\n```\n\n- [B](B.md)\n")

    apply_robustify(plan_robustify(tmp_path))

    links = find_robust_links((tmp_path / "DOC.md").read_text())
    assert len(links) == 1 and links[0].uuid == U_B  # robustified normally: not opted out


def test_ignore_file_wins_over_ignore_links(tmp_path):
    # FR-039 / Acceptance 5: both markers -> the stronger claim (003) applies; not an error.
    _w(tmp_path / "G.md", f"---\nuuid: {U_IDX}\n---\n<!-- darnlink-ignore-file -->\n{MARK}\n# G\n")
    index = build_index(tmp_path)
    assert U_IDX not in index.by_uuid  # dropped from the graph entirely, per FR-019
