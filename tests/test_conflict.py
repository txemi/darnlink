"""Path-vs-uuid conflict: when a robust link's path STILL resolves to a real file but the
anchored uuid lives in a DIFFERENT file, the two halves disagree. darnlink must NOT silently
follow the uuid and rewrite the path (that would hijack a link whose path was the real intent).
It must report a CONFLICT and leave the link untouched.

Reproduces a real-world case: a link to an existing `investigation...md` file carried a
mis-pasted uuid belonging to a different README; old behaviour rewrote the path to that README.
New behaviour: flag it, touch nothing.
"""
from pathlib import Path

from darnlink.frontmatter_index import build_index
from darnlink.repair import plan_repairs, apply_repairs
from darnlink.report import Kind

README_UUID = "182f5c02-d70d-495e-b8d5-1c76c454522a"
OTHER_UUID = "64369028-d843-43c5-9fa8-8fdb465bf5ad"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_conflict_when_path_resolves_but_uuid_lives_elsewhere(tmp_path):
    # The uuid lives in the README; the link's PATH points to a different, existing file.
    _w(tmp_path / "README.md", f"---\nuuid: {README_UUID}\n---\n# Issue README\n")
    _w(tmp_path / "investigacion.md", "# Investigación (no frontmatter)\n")  # exists, no uuid
    _w(
        tmp_path / "source.md",
        f"Detalle en [investigación](investigacion.md) <!-- uuid: {README_UUID} -->.\n",
    )

    before = (tmp_path / "source.md").read_text()
    index = build_index(tmp_path)
    result = plan_repairs(tmp_path, index)
    apply_repairs(result)

    # nothing rewritten, and it is reported as a conflict (not a repair)
    assert result.new_content == {}
    assert (tmp_path / "source.md").read_text() == before
    assert any(f.kind is Kind.CONFLICT for f in result.findings)
    assert not any(f.kind is Kind.REPAIR for f in result.findings)


def test_conflict_also_when_path_target_has_a_different_uuid(tmp_path):
    # Harder variant: the path target is itself a real doc with its OWN (different) uuid.
    _w(tmp_path / "README.md", f"---\nuuid: {README_UUID}\n---\n# README\n")
    _w(tmp_path / "investigacion.md", f"---\nuuid: {OTHER_UUID}\n---\n# Investigación\n")
    _w(
        tmp_path / "source.md",
        f"[investigación](investigacion.md) <!-- uuid: {README_UUID} -->\n",
    )

    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert result.new_content == {}
    assert any(f.kind is Kind.CONFLICT for f in result.findings)


def test_genuine_move_still_repairs(tmp_path):
    # Guard: when the path is truly stale (does not resolve), it is a move, not a conflict — repair.
    _w(tmp_path / "old" / "B.md", f"---\nuuid: {OTHER_UUID}\n---\n# B\n")
    _w(tmp_path / "A.md", f"[B](old/B.md) <!-- uuid: {OTHER_UUID} -->\n")
    (tmp_path / "new").mkdir()
    (tmp_path / "old" / "B.md").rename(tmp_path / "new" / "B.md")

    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert any(f.kind is Kind.REPAIR for f in result.findings)
    assert not any(f.kind is Kind.CONFLICT for f in result.findings)


def test_67_a_trailing_space_in_the_path_is_a_repair_not_an_unhealable_conflict(tmp_path):
    """#67: a trailing space made `names_md` false, so a plain FILE link with a stray space in its
    destination was misread as a DIRECTORY link — its uuid then "lives in a non-README file", which
    reads exactly like `test_conflict_when_path_resolves_but_uuid_lives_elsewhere` above, except the
    diagnosis is false: path and uuid actually agree, only the trailing space confused the classifier.

    Before the fix this was reported CONFLICT and, unlike a real conflict, `--write` could never heal
    it either — the gate stayed red permanently over a link that was never actually broken.

    After: `names_md` strips before checking the suffix, so this is correctly seen as a FILE link
    whose raw destination (with the space) does not resolve — an ordinary stale link, healed like
    any other. The rewrite also drops the stray space as a side effect of writing a fresh path, which
    is the right outcome, not just an acceptable one: nothing about a trailing space was meaningful.
    """
    _w(tmp_path / "old" / "B.md", f"---\nuuid: {OTHER_UUID}\n---\n# B\n")
    _w(tmp_path / "A.md", f"[x](old/B.md ) <!-- uuid: {OTHER_UUID} -->\n")  # note the space before `)`

    result = plan_repairs(tmp_path, build_index(tmp_path))
    apply_repairs(result)

    assert any(f.kind is Kind.REPAIR for f in result.findings), result.findings
    assert not any(f.kind is Kind.CONFLICT for f in result.findings), result.findings
    assert (tmp_path / "A.md").read_text() == f"[x](old/B.md) <!-- uuid: {OTHER_UUID} -->\n"


def test_67_a_genuine_directory_conflict_with_no_trailing_space_still_flags(tmp_path):
    """Guard against overcorrecting #67: stripping whitespace must not widen `names_md` into
    accepting things that are genuinely directory links. A real directory whose uuid lives in a
    file that is not its README is still a real conflict — the fix only touches whitespace, not the
    file-vs-directory rule itself.
    """
    _w(tmp_path / "notreadme.md", f"---\nuuid: {README_UUID}\n---\n# x\n")
    (tmp_path / "somedir").mkdir()
    _w(tmp_path / "A.md", f"[x](somedir) <!-- uuid: {README_UUID} -->\n")

    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert any(f.kind is Kind.CONFLICT for f in result.findings), result.findings
    assert result.new_content == {}


def test_directory_link_to_readme_is_not_a_conflict(tmp_path):
    # A robust link pointing at a DIRECTORY whose uuid lives in its README must never be flagged as a
    # path/uuid CONFLICT (the conflict rule keys on the path resolving to a real *file*; a directory
    # is not one). Since feature 011 (directory links) a directory link that already points at the
    # right directory is simply correct — a no-op — not a rewrite into the README *file* as before.
    _w(tmp_path / "issue" / "README.md", f"---\nuuid: {OTHER_UUID}\n---\n# Issue\n")
    _w(tmp_path / "A.md", f"[issue](issue/) <!-- uuid: {OTHER_UUID} -->\n")

    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert result.new_content == {}                       # already correct: nothing rewritten
    assert not any(f.kind is Kind.CONFLICT for f in result.findings)
