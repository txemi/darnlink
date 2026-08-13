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
    assert "dangling" in out              # but not silent: the count is stated
    # …and not enumerated. On the trees this axis lands on, one line per finding would bury the
    # findings that actually gate the build. `--json` carries them for machines; the gate recipe
    # prints them when its dangling axis is switched on.
    assert "nope.md" not in out


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


def test_finding_carries_the_line_number(tmp_path):
    """FR-041: `file` alone means hunting for the link by hand in a long document."""
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\nfiller\n\n[x](gone.md)\n")

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1 and found[0].detail.startswith("line 7:")


def test_encoded_absolute_path_does_not_escape_the_local_rule(tmp_path):
    """An encoded href can decode into something FR-046 excludes — the rule must apply to both.

    `%2Fetc%2Fpasswd` passes `is_local_relative` while encoded, so judging only the raw spelling
    would let the encoding walk around the rule: the finding would be suppressed merely because
    `/etc/passwd` happens to exist on the machine running the scan.
    """
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](%2Fetc%2Fpasswd)\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_encoded_scheme_is_not_reported(tmp_path):
    """The mirror case: `http%3A//example.com` decodes to a URL, which is never a dangling path."""
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](http%3A//example.com/nope.md)\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_missing_encoded_path_reports_the_decoded_target(tmp_path):
    """When it IS dangling, name the path the link denotes — that is the one to look for on disk."""
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](my%20missing%20file.md)\n")

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1
    assert "my missing file.md" in found[0].detail   # decoded, not %20
    assert "my%20missing%20file.md" in found[0].detail  # and the link as written


def test_image_embed_with_an_empty_alt_is_reported(tmp_path):
    """FR-051: `![](gone.png)` — the shape pandoc emits for every image in a converted .docx/.odt.

    `MD_LINK_RE` required at least one character of link text, so a link whose text is empty did not
    match *at all*. That is the worst failure mode a gate has: the link was not reported as bad, it
    was absent, and the axis printed `dangling: 0` over a tree full of broken embeds. Regression
    #52 — measured on one real corpus in its own gate scope: 127 links with empty text, 7 of them
    pointing at a target that does not exist, and the axis reported `dangling: 0`.
    """
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n![](gone.png)\n")

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1 and "gone.png" in found[0].detail


def test_empty_alt_image_that_exists_is_not_reported(tmp_path):
    """The other half of the pin: widening the regex must not invent findings."""
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n![](there.png)\n")
    _w(tmp_path / "there.png", "bytes\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_pandoc_attribute_suffix_does_not_hide_the_target(tmp_path):
    """#52 reported the `{width="…"}` suffix as the cause. It is not — but it must keep working.

    `![alt](x){width="1.1in"}` was already visible: the regex stops at the `)` and never looks at
    what follows. This pins that the suffix does not hide the target; that the suffix stays OUT of
    the match span is a separate property, and it needs a separate test — see
    `test_robustify.test_write_leaves_any_pandoc_attribute_suffix_untouched`, because detection
    alone cannot tell the two apart.
    """
    _w(tmp_path / "doc.md", f'---\nuuid: {U_A}\n---\n\n![](gone.png){{width="1.1in"}}\n')

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1 and "gone.png" in found[0].detail


def test_a_plain_link_with_empty_text_is_reported_too(tmp_path):
    """Not an image-only bug: `[](gone.md)` was equally invisible, and is a link like any other."""
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[](gone.md)\n")

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1 and "gone.md" in found[0].detail


def test_a_non_empty_alt_with_the_pandoc_suffix_is_still_seen(tmp_path):
    """The other half of the suffix pin: a link WITH text and a `{…}` suffix must keep working.

    The old regex already matched this one, so it guards the direction the empty-alt cases cannot:
    that widening the *text* did not disturb a link that was never affected.
    """
    _w(tmp_path / "doc.md", f'---\nuuid: {U_A}\n---\n\n![shot](gone.png){{width="1.1in"}}\n')

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1 and "gone.png" in found[0].detail


def test_a_whitespace_only_href_is_not_a_dangling_target(tmp_path):
    """FR-052: `[]( )` names no destination, so there is nothing to check.

    `[]()` never matched (`href` is `[^)]+`) but `[]( )` does, and resolving it gives the linking
    file's own directory with a blank name — a finding reading `line 5:  : target does not exist`,
    which names nothing anyone can go and look for. Widening the *text* must not smuggle in a
    finding about the *href*.
    """
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[]( )\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_a_percent_encoded_space_is_content_not_a_delimiter(tmp_path):
    """`[](%20)` is NOT the same link as `[]( )` — and an earlier version of this test said it was.

    FR-052 drops the whitespace that *delimits* a destination, and a delimiter exists only in the
    source. `%20` is an escape: it is content. Verified against the reference implementation
    (`cmark`), which emits `href="%20"` here and `href="a.md"` for `[x]( a.md )` — it strips the one
    and keeps the other.

    The version of this test that asserted "clean" was pinning a **false green**: with the strip
    applied after decoding, `[x](%20x.md)` resolved to `x.md`, so a link to a missing file was
    silently answered by an existing neighbour.

    Both spellings are in one fixture so the *contrast* is what is pinned, not two separate facts.

    ⚠️ The obvious fixture — a bare `[](%20)`, destination `" "` — is **not** used, and the reason is
    worth writing down: Windows trims trailing spaces from a path component, so `dir/ ` normalises to
    `dir`, which exists, and the link is not dangling **there**. That is the filesystem's answer, not
    darnlink's, and this axis exists to ask the filesystem. A platform-dependent fixture would have
    pinned Linux's answer as if it were the rule. It was caught by the Windows matrix in CI, not
    here.
    """
    _w(tmp_path / "x.md", "# x\n")                                   # the neighbour, present
    _w(tmp_path / "kept.md", f"---\nuuid: {U_A}\n---\n\n[a](%20x.md)\n")   # escape: content
    _w(tmp_path / "gone.md", f"---\nuuid: {U_A}\n---\n\n[b]( x.md )\n")    # literal: delimiter

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1, f"the two spellings were conflated: {found}"
    assert "%20x.md" in found[0].detail          # the encoded one is dead: it denotes " x.md"
    assert found[0].file == tmp_path / "kept.md"  # …and the literal one is not


def test_an_encoded_space_names_a_different_file_from_a_literal_one(tmp_path):
    """The false green and the false red of the same defect, pinned as one pair.

    `a.md` exists; `[x](%20a.md)` denotes `" a.md"`, which does not. Stripping after decoding made
    the first answer the second — clean over a broken link. And with `" a.md"` present instead, the
    same bug reported the link dead while naming `a.md`, a path the link never had: a false red on a
    live file, pointing the reader at the wrong neighbour.

    Reaches the encoded branch specifically. The literal-`\\xa0` test above cannot: with no escape in
    the href the decoded and raw forms are identical, so half of this function is never exercised.
    """
    _w(tmp_path / "one" / "a.md", "# a\n")
    _w(tmp_path / "one" / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x](%20a.md)\n")

    found = _dangling(plan_robustify(tmp_path / "one"))
    assert len(found) == 1, f"an encoded space was treated as a delimiter: {found}"
    assert "%20a.md" in found[0].detail                       # the link as written
    # The path it really denotes. Built from `Path`, not spelled with a `/`: the detail carries a
    # native path, so a hard-coded separator passes on Linux and fails on Windows — which is what
    # the CI matrix caught here.
    assert str(tmp_path / "one" / " a.md") in found[0].detail


def test_whitespace_before_a_bare_fragment_is_not_a_dangling_target(tmp_path):
    """`[x]( #section)` is a legal in-page anchor, and FR-046 says a bare fragment is never reported.

    Splitting the fragment leaves a path of pure whitespace, so this is FR-052's case — but reaching
    it requires the guard to sit *after* `split_fragment`. Before that, this was reported as a dead
    link: not merely a cosmetic finding, a false positive on valid CommonMark.
    """
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x]( #section)\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_whitespace_around_a_real_destination_is_stripped(tmp_path):
    """FR-052: CommonMark does not count the whitespace around a destination as part of it.

    `[x]( B.md )` denotes `B.md`. Judging it literally resolves to `dir/ B.md `, which exists under
    no spelling, so a link that renders and works was reported dead. This is the same rule as the
    empty case — `[x]( )` denotes nothing, `[x]( B.md )` denotes `B.md` — and an earlier version
    closed only the first half while the spec argued for both.
    """
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x]( B.md )\n")
    _w(tmp_path / "B.md", "# B\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_whitespace_around_a_missing_destination_still_dangles(tmp_path):
    """The other half: stripping must not swallow the finding, only the spelling."""
    _w(tmp_path / "doc.md", f"---\nuuid: {U_A}\n---\n\n[x]( gone.md )\n")

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 1 and "gone.md" in found[0].detail


def test_encoded_and_fragment_spellings_of_a_real_target_are_stripped(tmp_path):
    """FR-052 has to be applied where its value is USED, not only where it is tested.

    A version of this rule computed the stripped path for the emptiness check and then resolved
    `href.strip()` — a different string. `.strip()` on the raw href cannot reach a space sitting
    before a `#`, so these resolved to `dir/B.md ` and were reported dead while `B.md` sat there.

    A false RED on a live file is not the mirror of a false green, it is how a gate gets switched
    off — so it is pinned per spelling, not as one case.

    ⚠️ `%20B.md ` was in this list and has been **removed**, because listing it here was itself the
    defect. Its trailing space is a delimiter and goes; its `%20` is content and stays, so the link
    denotes `" B.md"` and is dead when only `B.md` exists. Asserting it clean pinned a false green —
    a test enforcing the bug it was written to prevent. It now lives in
    `test_an_encoded_space_names_a_different_file_from_a_literal_one`, asserting the opposite.
    """
    _w(tmp_path / "B.md", "# B\n")
    for i, href in enumerate([" B.md #s", "B.md #s", " B.md "]):
        _w(tmp_path / f"doc{i}.md", f"---\nuuid: {U_A}\n---\n\n[x]({href})\n")

    assert _dangling(plan_robustify(tmp_path)) == []


def test_only_ascii_whitespace_is_stripped_from_a_destination(tmp_path):
    """FR-052 strips CommonMark whitespace, which is ASCII. `\\xa0` is an ordinary character.

    `str.strip()` removes everything Python calls whitespace — NBSP, the ideographic space, and
    ~20 more — but CommonMark counts only space, tab, LF, VT, FF and CR. A file really can be named
    `\\xa0a.md`, so stripping the NBSP made a link to a MISSING file resolve to an existing
    neighbour and report **clean**: a false green, in the function this feature owns.

    Not academic: NBSP is what a Word or HTML paste produces, which is the same corpus of converted
    documents that motivated the whole feature.
    """
    _w(tmp_path / "a.md", "# a\n")          # exists — the neighbour a bare .strip() would find
    for i, href in enumerate(["\xa0a.md", "\u3000a.md", "a.md\xa0"]):
        _w(tmp_path / f"doc{i}.md", f"---\nuuid: {U_A}\n---\n\n[x]({href})\n")

    found = _dangling(plan_robustify(tmp_path))
    assert len(found) == 3, f"a non-ASCII space was treated as whitespace: {found}"


def test_every_character_of_the_commonmark_whitespace_set_is_stripped(tmp_path):
    """All six, one file each — because a set is a claim about six characters, not about one.

    Only the space was exercised, so dropping `\\t`, `\\r`, `\\x0b` or `\\x0c` from the constant left
    the suite green. VT and FF are the surprising members and the easiest to "tidy away"; they are
    in CommonMark's definition, verified against the reference implementation, so they are pinned
    here rather than defended in a comment.

    Uses a NON-newline set only where a newline could not appear inside a link destination anyway.
    """
    _w(tmp_path / "B.md", "# B\n")
    for i, ws in enumerate([" ", "\t", "\r", "\x0b", "\x0c"]):
        _w(tmp_path / f"doc{i}.md", f"---\nuuid: {U_A}\n---\n\n[x]({ws}B.md{ws})\n")

    found = _dangling(plan_robustify(tmp_path))
    assert found == [], f"a CommonMark whitespace character was kept as part of the path: {found}"
