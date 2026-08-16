"""Feature 017 — `absolute_local_path`: a plain link written as an absolute filesystem path.

`is_local_relative` excludes anything starting with `/` (FR-046 draws that line for `_dangling_target`
too), so a link like `[x](/home/user/notes.md)` fell out of the scan silently: not `dangling` (that
axis shares the same exclusion) and not `out_of_scope` (that one names a real location outside
`--root`; an absolute path names no root-relative location at all). It received no check of any kind
— even though, unlike a relative link, it can never resolve on any clone but the one that wrote it.

Report-only, same as `dangling`: nothing is ever written in response to this finding, and it is
deliberately absent from `check`'s exit code (FR-049's reasoning applies here unchanged — folding a
brand-new axis into the exit code would turn every consumer's next `darnlink check` red with no
ratchet to climb down from).
"""
from pathlib import Path

from darnlink.report import Kind
from darnlink.robustify import plan_robustify, apply_robustify

U_A = "aaaaaaaa-1111-2222-3333-444444444444"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _abs_local(result, f: Path | None = None):
    return [x for x in result.findings
            if x.kind is Kind.ABSOLUTE_LOCAL_PATH and (f is None or x.file == f)]


def test_absolute_local_path_is_reported(tmp_path):
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](/home/user/notes.md)\n")

    result = plan_robustify(tmp_path)
    apply_robustify(result)
    found = _abs_local(result)

    assert len(found) == 1
    assert "/home/user/notes.md" in found[0].detail
    # report-only: byte-for-byte, like dangling (FR-042's guarantee extends to this axis)
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == \
        f"---\nuuid: {U_A}\n---\n\n[x](/home/user/notes.md)\n"


def test_relative_link_is_not_reported(tmp_path):
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](sibling.md)\n")
    _w(tmp_path / "sibling.md", "# s\n")

    assert _abs_local(plan_robustify(tmp_path)) == []


def test_protocol_relative_url_is_not_reported(tmp_path):
    """`//example.com/x` starts with `/` but is a scheme, not a filesystem path."""
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](//example.com/notes.md)\n")

    assert _abs_local(plan_robustify(tmp_path)) == []


def test_web_and_mailto_links_are_not_reported(tmp_path):
    _w(tmp_path / "doc.md",
       f"---\nuuid: {U_A}\n---\n\n[a](https://example.com/x.md)\n[b](mailto:x@y.z)\n")

    assert _abs_local(plan_robustify(tmp_path)) == []


def test_bare_fragment_is_not_reported(tmp_path):
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](#section)\n")

    assert _abs_local(plan_robustify(tmp_path)) == []


def test_encoded_absolute_path_is_caught_too(tmp_path):
    """The mirror of dangling's FR-047 case: `%2Fetc%2Fpasswd` decodes to an absolute path.

    Dangling deliberately does NOT report this href (it decodes away from `is_local_relative`
    before existence is even checked). This axis exists to catch exactly what that one lets go:
    the decoded shape is still an absolute path, so it must not escape via encoding either.
    """
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](%2Fetc%2Fpasswd)\n")

    found = _abs_local(plan_robustify(tmp_path))
    assert len(found) == 1
    assert "/etc/passwd" in found[0].detail


def test_out_of_scope_relative_link_is_not_absolute_local_path(tmp_path):
    """A `../`-escaping RELATIVE link that lands outside root is `out_of_scope`, a different axis.

    This is the case the analysis that led to this feature was actually about: a relative link
    that escapes the scanned root and happens to resolve to something that exists (e.g. a sibling
    repo cloned next to this one). It is not this axis's business — it names a real root-relative
    path, unlike an absolute one, which names none.
    """
    outside = tmp_path.parent / "sibling_repo"
    _w(outside / "README.md", f"---\nuuid: bbbbbbbb-1111-2222-3333-444444444444\n---\n# sibling\n")
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](../sibling_repo/README.md)\n")

    result = plan_robustify(tmp_path)
    assert _abs_local(result) == []
    assert [f for f in result.findings if f.kind is Kind.OUT_OF_SCOPE]


def test_code_spans_and_fences_are_not_links(tmp_path):
    _w(tmp_path / "doc.md",
       f"---\nuuid: {U_A}\n---\n\n`[a](/home/user/x.md)`\n\n```\n[b](/home/user/y.md)\n```\n")

    assert _abs_local(plan_robustify(tmp_path)) == []


def test_finding_carries_the_line_number(tmp_path):
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\nfiller\n\n[x](/etc/passwd)\n")

    found = _abs_local(plan_robustify(tmp_path))
    assert len(found) == 1 and found[0].detail.startswith("line 7:") and found[0].line == 7


def test_check_reports_it_without_changing_the_exit_code(tmp_path, capsys):
    """FR-049's reasoning, unchanged for this axis: it must not gate the day it lands."""
    from darnlink.cli import main

    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](/home/user/notes.md)\n")

    code = main(["check", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 0
    assert "absolute-local-path" in out
    assert "/home/user/notes.md" not in out  # counted, not enumerated in the text report


def test_check_json_carries_it_on_its_own_axis(tmp_path, capsys):
    import json as _json

    from darnlink.cli import main

    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](/home/user/notes.md)\n")

    code = main(["check", str(tmp_path), "--json"])
    payload = _json.loads(capsys.readouterr().out)

    assert code == 0 and payload["exit_code"] == 0
    assert payload["absolute_local_path"]["count"] == 1
    assert payload["integrity"]["failed"] is False and payload["strict"]["failed"] is False
