"""Feature 015 — `dangling`: a plain link whose target does not exist.

Today such a link falls out of the scan silently: it is not `unresolvable` (that is a *robust* link
whose uuid died) and not `robustify` (there is nothing to anchor). `_anchor_target` returns None both
for "the target is not anchorable" and for "the target is not there", and the caller cannot tell the
two apart. This feature names the second case.

Report-only: nothing is ever written in response to a `dangling` finding (FR-042).
"""
from pathlib import Path

from darnlink.report import Kind
from darnlink.robustify import plan_robustify, apply_robustify

U_A = "aaaaaaaa-1111-2222-3333-444444444444"
MARK_LINKS = "<!-- darnlink-ignore-links -->"
MARK_FILE = "<!-- darnlink-ignore-file -->"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _dangling(result, f: Path | None = None):
    return [x for x in result.findings
            if x.kind is Kind.DANGLING and (f is None or x.file == f)]


def test_acceptance_three_missing_targets_of_any_kind(tmp_path):
    """Cornerstone (FR-041/FR-043): .md, non-.md and a directory — three findings, nothing written."""
    doc = tmp_path / "doc.md"
    text = f"---\nuuid: {U_A}\n---\n\n[x](nope.md)\n[y](nope.csv)\n[z](nope/)\n"
    _w(doc, text)

    result = plan_robustify(tmp_path)
    apply_robustify(result)

    assert len(_dangling(result, doc)) == 3
    assert doc.read_text(encoding="utf-8") == text  # FR-042: report-only, byte-for-byte


def test_no_finding_once_the_targets_exist(tmp_path):
    """The other half of the acceptance test: create them and the findings disappear."""
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[y](there.csv)\n[z](dir/)\n")
    _w(tmp_path / "there.csv", "col\n")
    (tmp_path / "dir").mkdir()

    assert _dangling(plan_robustify(tmp_path)) == []


def test_existing_but_non_anchorable_target_is_not_dangling(tmp_path):
    """FR-044: a `.png` that IS there stays invisible — it was never anchorable, and that is fine.

    This is the distinction the feature exists to draw: 'not anchorable' and 'not there' used to be
    the same `None`.
    """
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[img](logo.png)\n")
    _w(tmp_path / "logo.png", "not really a png\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_directory_without_readme_is_not_dangling(tmp_path):
    """A real directory with no README is feature 012's business (create_readme), not a dead link."""
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[d](sub/)\n")
    (tmp_path / "sub").mkdir()

    assert _dangling(plan_robustify(tmp_path)) == []


def test_external_and_fragment_links_never_dangle(tmp_path):
    """FR-046: schemes, protocol-relative and bare fragments are not local paths."""
    _w(tmp_path / "doc.md",
       f"---\nuuid: {U_A}\n---\n\n[a](https://example.com/nope.md)\n[b](mailto:x@y.z)\n"
       f"[c](//example.com/nope.md)\n[d](#section)\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_fragment_is_stripped_before_resolving(tmp_path):
    """FR-046: `file.md#sec` is judged by `file.md` — present means no finding, absent means one."""
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[a](there.md#sec)\n[b](gone.md#sec)\n")
    _w(tmp_path / "there.md", "# there\n")

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1 and "gone.md#sec" in found[0].detail


def test_percent_encoded_path_that_exists_is_not_dangling(tmp_path):
    """FR-047: `my%20file.md` denotes `my file.md`. Judging it literally would cry wolf.

    darnlink's `resolve_href` does not decode, so a naive existence check on the raw href would
    report every percent-encoded link in the fleet — the kind of false positive that gets a gate
    bypassed.
    """
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[a](my%20file.md)\n")
    _w(tmp_path / "my file.md", "# spaces\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_code_spans_and_fences_are_not_links(tmp_path):
    """FR-045: composes with the existing span handling — an example is not a link."""
    _w(tmp_path / "doc.md",
       f"---\nuuid: {U_A}\n---\n\n`[a](nope.md)`\n\n```\n[b](nope.md)\n```\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_ignore_links_marker_suppresses_dangling(tmp_path):
    """FR-045: a file that opted out as a SOURCE reports nothing about its own links."""
    _w(tmp_path / "gen.md", f"---\nuuid: {U_A}\n---\n{MARK_LINKS}\n\n[x](nope.md)\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_ignore_file_marker_suppresses_dangling(tmp_path):
    """FR-045: an opted-out file is not scanned as a source at all."""
    _w(tmp_path / "out.md", f"---\nuuid: {U_A}\n---\n{MARK_FILE}\n\n[x](nope.md)\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_stale_robust_link_is_a_repair_not_a_dangling(tmp_path):
    """FR-048: the uuid is the authority. A robust link whose path drifted is about to be fixed."""
    _w(tmp_path / "target.md", f"---\nuuid: {U_A}\n---\n# t\n")
    _w(tmp_path / "doc.md",
       f"---\nuuid: bbbbbbbb-1111-2222-3333-444444444444\n---\n\n"
       f"[t](old/where.md) <!-- uuid: {U_A} -->\n")

    # A robust link is not a plain link, so the robustify pass must not claim it.
    assert _dangling(plan_robustify(tmp_path)) == []


def test_finding_names_the_link_and_the_resolved_path(tmp_path):
    """FR-041: the report has to be actionable without opening the file."""
    _w(tmp_path / "sub" / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](../gone.md)\n")

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1
    assert "../gone.md" in found[0].detail
    assert "gone.md" in found[0].detail
    assert found[0].file == tmp_path / "sub" / "doc.md"


def test_check_reports_dangling_without_changing_the_exit_code(tmp_path, capsys):
    """FR-049: the whole rollout depends on this.

    If `dangling` moved the exit code, every consumer repo would go red the moment it upgraded, and
    its only escape would be *lowering* its mode — turning a one-way ratchet into a relaxation. So
    the core names the finding and the gate recipe decides whether it bites.
    """
    from darnlink.cli import main

    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](nope.md)\n")

    code = main(["check", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 0                      # clean: nothing to repair, nothing to robustify
    assert "dangling" in out              # but not silent
    assert "nope.md" in out


def test_check_json_carries_dangling_on_its_own_axis(tmp_path, capsys):
    import json as _json

    from darnlink.cli import main

    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](nope.csv)\n")

    code = main(["check", str(tmp_path), "--json"])
    payload = _json.loads(capsys.readouterr().out)

    assert code == 0 and payload["exit_code"] == 0
    assert payload["dangling"]["count"] == 1
    assert payload["integrity"]["failed"] is False and payload["strict"]["failed"] is False


def test_image_embed_with_a_missing_target_is_reported(tmp_path):
    """FR-050: `![alt](gone.png)` is a path in a Markdown document like any other.

    `MD_LINK_RE` never excluded embeds, so they always travelled the plain-link path — they just died
    silently at `_anchor_target`, a `.png` being unanchorable. Naming the dangling case makes that
    visible, so it is pinned here as a decision rather than left to a regex.
    """
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n![shot](gone.png)\n")

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1 and "gone.png" in found[0].detail


def test_image_embed_that_exists_is_not_reported(tmp_path):
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n![shot](there.png)\n")
    _w(tmp_path / "there.png", "bytes\n")

    assert _dangling(plan_robustify(tmp_path)) == []
