"""A `<!-- uuid: X -->` that is not attached to any link.

The anchor only counts when it immediately follows the link's `)` (any whitespace, nothing else).
Put it one token further away -- typically past a closing `**` -- and the link is still plain, so
robustify wants to anchor it. Naively appending a second anchor leaves the file carrying the same
uuid twice, one of them attached to nothing, and every later run reports the tree clean: the litter
becomes permanent and silent.

These tests pin the intended behaviour: robustify MOVES an unambiguous detached anchor instead of
duplicating it, and says so; anything ambiguous is left alone and announced (Constitution II).
"""
from pathlib import Path

from darnlink.links import code_spans, find_detached_anchors, find_robust_links
from darnlink.report import Kind
from darnlink.robustify import apply_robustify, plan_robustify

TARGET = "aaaaaaaa-1111-2222-3333-444444444444"
OTHER = "bbbbbbbb-1111-2222-3333-444444444444"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _target(tmp_path: Path) -> None:
    _w(tmp_path / "B.md", f"---\nuuid: {TARGET}\n---\n# B\n")


def _anchors(text: str) -> int:
    return text.count(f"<!-- uuid: {TARGET} -->")


# --- find_detached_anchors -------------------------------------------------------------------

def test_find_detached_anchors_ignores_a_properly_attached_one():
    content = f"[B](B.md) <!-- uuid: {TARGET} -->\n"
    assert find_detached_anchors(content) == []


def test_find_detached_anchors_reports_one_past_a_bold_close():
    content = f"**text [B](B.md)** <!-- uuid: {TARGET} -->\n"
    found = find_detached_anchors(content)
    assert [d.uuid for d in found] == [TARGET]


def test_find_detached_anchors_skips_code_spans():
    """Like its siblings it takes the spans to skip; robustify passes the ones it already computed."""
    content = f"`<!-- uuid: {TARGET} -->` is the anchor syntax.\n"
    assert find_detached_anchors(content, code_spans(content)) == []


# --- robustify: the bug ----------------------------------------------------------------------

def test_robustify_moves_detached_anchor_instead_of_duplicating(tmp_path):
    """The regression: the anchor is already there, just misplaced. Move it, do not clone it."""
    _target(tmp_path)
    _w(tmp_path / "A.md", f"| x | **text [B](B.md)** <!-- uuid: {TARGET} --> |\n")

    apply_robustify(plan_robustify(tmp_path))

    a = (tmp_path / "A.md").read_text()
    assert _anchors(a) == 1, f"the anchor was duplicated: {a!r}"
    links = find_robust_links(a)
    assert len(links) == 1 and links[0].uuid == TARGET
    assert find_detached_anchors(a) == []
    assert "**text" in a and "**" in a  # surrounding markup preserved


def test_robustify_is_idempotent_after_moving_a_detached_anchor(tmp_path):
    _target(tmp_path)
    _w(tmp_path / "A.md", f"**[B](B.md)** <!-- uuid: {TARGET} -->\n")

    apply_robustify(plan_robustify(tmp_path))
    once = (tmp_path / "A.md").read_text()
    apply_robustify(plan_robustify(tmp_path))
    assert (tmp_path / "A.md").read_text() == once


def test_robustify_names_the_move_in_its_finding(tmp_path):
    _target(tmp_path)
    _w(tmp_path / "A.md", f"**[B](B.md)** <!-- uuid: {TARGET} -->\n")

    findings = [f for f in plan_robustify(tmp_path).findings if f.kind is Kind.ROBUSTIFY]
    assert len(findings) == 1
    assert "detached" in findings[0].detail.lower()


# --- robustify: what it must NOT touch --------------------------------------------------------

def test_detached_anchor_with_a_different_uuid_is_left_alone(tmp_path):
    """Only an exact uuid match is a misplaced anchor for THIS link (Constitution IV)."""
    _target(tmp_path)
    _w(tmp_path / "A.md", f"**[B](B.md)** <!-- uuid: {OTHER} -->\n")

    apply_robustify(plan_robustify(tmp_path))

    a = (tmp_path / "A.md").read_text()
    assert f"<!-- uuid: {OTHER} -->" in a       # the stray one is not ours to remove
    assert _anchors(a) == 1                     # the link got its own, correct anchor


def test_two_trailing_strays_are_left_alone_and_the_reason_is_named(tmp_path):
    """Two candidates behind one link: which is the anchor? Unknowable, so neither moves.

    Second Copilot review, PR #35: the warning used to blame causes that did not apply here (sitting
    before the link / several claimants), which is the same wrong-place-to-look failure this whole
    change is about. It must name the reason that is actually true.
    """
    _target(tmp_path)
    _w(tmp_path / "A.md", f"**[B](B.md)** <!-- uuid: {TARGET} --> x <!-- uuid: {TARGET} -->\n")

    result = plan_robustify(tmp_path)
    apply_robustify(result)

    a = (tmp_path / "A.md").read_text()
    assert len(find_detached_anchors(a)) == 2   # both strays survive untouched
    detail = next(f.detail for f in result.findings if f.kind is Kind.ROBUSTIFY)
    assert "more than one such anchor trails the link" in detail
    assert "before the link" not in detail       # the cause that does NOT apply is not claimed
    assert "could own it" not in detail


def test_detached_anchor_before_the_link_is_never_absorbed(tmp_path):
    """Only a TRAILING stray can be the link's own anchor (Copilot review, PR #35).

    The bug's mechanism is a comment that sat right after the `)` and fell out of the grammar when a
    closing token slipped in between — that always leaves the stray *after* the link. One placed
    before it got there some other way, by hand, and moving it would be the guess we refuse to make.
    """
    _target(tmp_path)
    _w(tmp_path / "A.md", f"<!-- uuid: {TARGET} --> see [B](B.md)\n")

    result = plan_robustify(tmp_path)
    apply_robustify(result)

    a = (tmp_path / "A.md").read_text()
    assert a.startswith(f"<!-- uuid: {TARGET} --> see ")  # left byte-for-byte where it was
    assert len(find_robust_links(a)) == 1                 # the link still got its own anchor
    assert len(find_detached_anchors(a)) == 1             # the stray survives
    details = " ".join(f.detail for f in result.findings if f.kind is Kind.ROBUSTIFY)
    assert "detached" in details.lower()                  # and the duplicate is announced, not silent


def test_detached_anchor_on_another_line_is_left_alone(tmp_path):
    _target(tmp_path)
    _w(tmp_path / "A.md", f"<!-- uuid: {TARGET} -->\n\n[B](B.md)\n")

    apply_robustify(plan_robustify(tmp_path))

    a = (tmp_path / "A.md").read_text()
    assert _anchors(a) == 2                     # untouched line + newly anchored link
    assert len(find_detached_anchors(a)) == 1


def test_detached_anchor_inside_code_is_never_absorbed(tmp_path):
    _target(tmp_path)
    _w(tmp_path / "A.md", f"[B](B.md) and `<!-- uuid: {TARGET} -->` shown as syntax\n")

    apply_robustify(plan_robustify(tmp_path))

    a = (tmp_path / "A.md").read_text()
    assert f"`<!-- uuid: {TARGET} -->`" in a     # the example stays verbatim
    assert len(find_robust_links(a)) == 1


def test_two_candidate_links_on_one_line_leave_the_stray_anchor_alone(tmp_path):
    """Ambiguous: two plain links on the line would both claim the same detached anchor.

    Whose anchor is it? Nothing in the file says, and guessing would be a heuristic (Constitution
    IV). So the stray one is left exactly where it is -- but the report says so, because a silently
    duplicated uuid is the very failure this change exists to stop (Constitution II).
    """
    _target(tmp_path)
    _w(tmp_path / "A.md", f"**[B](B.md)** and **[again](B.md)** <!-- uuid: {TARGET} -->\n")

    result = plan_robustify(tmp_path)
    apply_robustify(result)

    a = (tmp_path / "A.md").read_text()
    assert len(find_robust_links(a)) == 2       # both links anchored...
    assert len(find_detached_anchors(a)) == 1   # ...and the stray one untouched
    details = " ".join(f.detail for f in result.findings if f.kind is Kind.ROBUSTIFY)
    assert "detached" in details.lower()        # never silent
