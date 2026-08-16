from pathlib import Path

from darnlink.frontmatter_edit import read_uuid_from_content
from darnlink.links import find_robust_links
from darnlink.report import Kind
from darnlink.robustify import plan_robustify, apply_robustify

EXISTING = "11111111-2222-3333-4444-555555555555"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_robustify_reuses_existing_uuid(tmp_path):
    _w(tmp_path / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    _w(tmp_path / "A.md", "See [B](B.md) plain.\n")
    result = plan_robustify(tmp_path)
    apply_robustify(result)
    a = (tmp_path / "A.md").read_text()
    links = find_robust_links(a)
    assert len(links) == 1
    assert links[0].href == "B.md"          # path unchanged
    assert links[0].uuid == EXISTING        # reused existing uuid
    # B untouched (it already had a uuid)
    assert (tmp_path / "B.md").read_text() == f"---\nuuid: {EXISTING}\n---\n# B\n"


def test_robustify_adds_uuid_to_target_with_frontmatter(tmp_path):
    _w(tmp_path / "B.md", "---\ntitle: B\n---\n# B\n")  # frontmatter but no uuid
    _w(tmp_path / "A.md", "[B](B.md)\n")
    result = plan_robustify(tmp_path)
    apply_robustify(result)
    b = (tmp_path / "B.md").read_text()
    u = read_uuid_from_content(b)
    assert u is not None
    assert "title: B" in b                  # existing frontmatter preserved
    a_link = find_robust_links((tmp_path / "A.md").read_text())[0]
    assert a_link.uuid == u                  # link annotated with the target's new uuid


def test_robustify_skips_target_without_frontmatter_by_default(tmp_path):
    _w(tmp_path / "B.md", "# B (no frontmatter)\n")
    _w(tmp_path / "A.md", "[B](B.md)\n")
    result = plan_robustify(tmp_path, create_frontmatter=False)
    assert result.new_content == {}
    assert any(f.kind is Kind.NO_FRONTMATTER for f in result.findings)


def test_robustify_creates_frontmatter_when_opted_in(tmp_path):
    _w(tmp_path / "B.md", "# B (no frontmatter)\n")
    _w(tmp_path / "A.md", "[B](B.md)\n")
    result = plan_robustify(tmp_path, create_frontmatter=True)
    apply_robustify(result)
    b = (tmp_path / "B.md").read_text()
    assert b.startswith("---\nuuid: ")
    assert "# B (no frontmatter)" in b
    assert find_robust_links((tmp_path / "A.md").read_text())[0].uuid == read_uuid_from_content(b)


def test_robustify_skips_self_links(tmp_path):
    # a file linking to itself (e.g. the autogrid `path` row) must NOT be robustified
    _w(tmp_path / "A.md", f"---\nuuid: {EXISTING}\n---\n| path | [A.md](A.md) |\n")
    result = plan_robustify(tmp_path)
    assert result.new_content == {}


def test_robustify_idempotent(tmp_path):
    _w(tmp_path / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    _w(tmp_path / "A.md", "[B](B.md)\n")
    apply_robustify(plan_robustify(tmp_path))
    # second run: nothing to do
    assert plan_robustify(tmp_path).new_content == {}


def test_robustify_ignores_urls_and_non_md(tmp_path):
    _w(tmp_path / "A.md", "[site](https://x.com/a.md) and [img](pic.png) and [anchor](#sec)\n")
    result = plan_robustify(tmp_path)
    assert result.new_content == {}


def test_robustify_leaves_links_inside_code_untouched(tmp_path):
    # SC-006: a link inside a fenced block and one inside inline code must not be robustified;
    # the real prose link in the same file still is.
    _w(tmp_path / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    _w(
        tmp_path / "A.md",
        "Prose [B](B.md)\n"
        "```markdown\n"
        "[B](B.md)\n"
        "```\n"
        "inline `[B](B.md)` end\n",
    )
    apply_robustify(plan_robustify(tmp_path))
    a = (tmp_path / "A.md").read_text()
    # the fenced and inline examples are byte-for-byte intact
    assert "```markdown\n[B](B.md)\n```" in a
    assert "`[B](B.md)`" in a
    # exactly one robust link emitted (the prose one)
    links = find_robust_links(a)
    assert len(links) == 1 and links[0].uuid == EXISTING


def test_robustify_skips_file_with_ignore_marker_as_source(tmp_path):
    # SC-009: a file carrying the marker is not robustified, even with valid plain links inside.
    _w(tmp_path / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    _w(tmp_path / "G.md", "<!-- darnlink-ignore-file -->\ngenerated [B](B.md)\n")
    result = plan_robustify(tmp_path)
    apply_robustify(result)
    g = (tmp_path / "G.md").read_text()
    assert g == "<!-- darnlink-ignore-file -->\ngenerated [B](B.md)\n"  # byte-for-byte intact
    assert (tmp_path / "G.md") in result.ignored


def test_robustify_deny_list_skips_regenerated_target(tmp_path):
    # SC-015: with --create-frontmatter, a curated no-frontmatter target gets a uuid, but a
    # regenerated one named in the deny-list is left plain and reported.
    _w(tmp_path / "analysis.md", "# analysis (no frontmatter)\n")
    _w(tmp_path / "content.md", "# content (regenerated, no frontmatter)\n")
    _w(tmp_path / "A.md", "see [an](analysis.md) and [co](content.md)\n")
    result = plan_robustify(
        tmp_path, create_frontmatter=True, no_create_globs=("content.md",)
    )
    apply_robustify(result)
    # curated target: uuid created, link robustified
    an = (tmp_path / "analysis.md").read_text()
    assert an.startswith("---\nuuid: ")
    # regenerated target: untouched
    assert (tmp_path / "content.md").read_text() == "# content (regenerated, no frontmatter)\n"
    a = (tmp_path / "A.md").read_text()
    links = {l.href: l.uuid for l in find_robust_links(a)}
    assert links.get("analysis.md") == read_uuid_from_content(an)  # robustified
    assert "content.md" not in links                                # left plain
    assert "[co](content.md)" in a
    # the denied target is reported as deny_listed (not the misleading no_frontmatter message)
    assert any(
        f.kind is Kind.DENY_LISTED and "content.md" in f.detail for f in result.findings
    )
    assert not any(f.kind is Kind.NO_FRONTMATTER for f in result.findings)


def test_robustify_deny_list_glob(tmp_path):
    # User Story 2: globs in the deny-list match by basename.
    _w(tmp_path / "PROJ-1533.md", "# jira export (no frontmatter)\n")
    _w(tmp_path / "notes.md", "# notes (no frontmatter)\n")
    _w(tmp_path / "A.md", "[j](PROJ-1533.md) and [n](notes.md)\n")
    result = plan_robustify(
        tmp_path, create_frontmatter=True, no_create_globs=("PROJ-*.md",)
    )
    apply_robustify(result)
    assert (tmp_path / "PROJ-1533.md").read_text() == "# jira export (no frontmatter)\n"  # denied
    assert (tmp_path / "notes.md").read_text().startswith("---\nuuid: ")                  # created
    links = {l.href for l in find_robust_links((tmp_path / "A.md").read_text())}
    assert "notes.md" in links and "PROJ-1533.md" not in links


def test_robustify_deny_list_reuses_existing_uuid(tmp_path):
    # FR-030: the deny-list gates creation only; a denied target that already has a uuid is reused.
    _w(tmp_path / "content.md", f"---\nuuid: {EXISTING}\n---\n# content\n")
    _w(tmp_path / "A.md", "[co](content.md)\n")
    result = plan_robustify(
        tmp_path, create_frontmatter=True, no_create_globs=("content.md",)
    )
    apply_robustify(result)
    a_link = find_robust_links((tmp_path / "A.md").read_text())[0]
    assert a_link.uuid == EXISTING  # reused, not skipped


def test_robustify_empty_deny_list_is_noop(tmp_path):
    # SC-016: an empty deny-list reproduces prior behavior exactly.
    _w(tmp_path / "B.md", "# B (no frontmatter)\n")
    _w(tmp_path / "A.md", "[B](B.md)\n")
    with_empty = plan_robustify(tmp_path, create_frontmatter=True, no_create_globs=())
    apply_robustify(with_empty)
    b = (tmp_path / "B.md").read_text()
    assert b.startswith("---\nuuid: ")  # created, same as before the feature


def test_robustify_deny_list_gates_insertion_into_existing_frontmatter(tmp_path):
    # Edge case: a denied target with valid frontmatter but no uuid is NOT given one (both
    # creation paths are gated) — "never give this file a uuid".
    _w(tmp_path / "content.md", "---\ntitle: gen\n---\n# content\n")
    _w(tmp_path / "A.md", "[co](content.md)\n")
    result = plan_robustify(
        tmp_path, create_frontmatter=True, no_create_globs=("content.md",)
    )
    apply_robustify(result)
    assert (tmp_path / "content.md").read_text() == "---\ntitle: gen\n---\n# content\n"  # untouched
    assert "[co](content.md)" in (tmp_path / "A.md").read_text()  # left plain
    assert any(
        f.kind is Kind.DENY_LISTED and "content.md" in f.detail for f in result.findings
    )


def test_robustify_deny_list_applies_without_create_frontmatter(tmp_path):
    # Intentional semantics: a deny-listed target is never given a uuid, regardless of
    # --create-frontmatter. A regenerated file with existing frontmatter (no uuid) is left untouched
    # even without --create-frontmatter (where the default would otherwise insert a uuid line).
    _w(tmp_path / "content.md", "---\ntitle: gen\n---\n# content\n")
    _w(tmp_path / "A.md", "[co](content.md)\n")
    result = plan_robustify(
        tmp_path, create_frontmatter=False, no_create_globs=("content.md",)
    )
    apply_robustify(result)
    assert (tmp_path / "content.md").read_text() == "---\ntitle: gen\n---\n# content\n"  # untouched
    assert "[co](content.md)" in (tmp_path / "A.md").read_text()                        # left plain
    assert any(f.kind is Kind.DENY_LISTED for f in result.findings)


def test_robustify_ignored_target_gets_no_uuid(tmp_path):
    # SC-009: an ignored file that is the target of a plain link never joins the graph.
    g_before = "<!-- darnlink-ignore-file -->\n# generated\n"
    _w(tmp_path / "G.md", g_before)
    _w(tmp_path / "A.md", "see [G](G.md)\n")
    result = plan_robustify(tmp_path, create_frontmatter=True)
    apply_robustify(result)
    assert (tmp_path / "G.md").read_text() == g_before           # G untouched, no uuid added
    assert (tmp_path / "A.md").read_text() == "see [G](G.md)\n"  # link left plain
    # a link to an ignored target must NOT be reported as no_frontmatter (misleading)
    assert not any(fi.kind is Kind.NO_FRONTMATTER for fi in result.findings)


def test_write_preserves_the_bang_of_an_image_embed(tmp_path):
    """FR-051: the widening routes empty-alt embeds into the WRITE path for the first time.

    The `!` sits outside the match span, so a rewrite must leave it in place. Detection cannot pin
    this — the finding looks identical either way — and a rewrite that swallowed it would silently
    turn every repaired image into a text link, which renders as a filename instead of a picture.
    Seeded before writing this: an emitter that consumes the `!` leaves the whole suite green.
    """
    _w(tmp_path / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    _w(tmp_path / "A.md", "see ![](B.md) here\n")

    apply_robustify(plan_robustify(tmp_path))

    a = (tmp_path / "A.md").read_text()
    # Assert the WHOLE line, because every weaker form is satisfiable while the behaviour is wrong:
    # `"!" in a` is true from the anchor's own `<!--`; `a.startswith("!")` only holds while the
    # fixture begins with the link; and `"![](B.md)" in a` is satisfied by `!![](B.md)`, which is
    # what an emitter that adds a bang unconditionally would produce. The fixture is deterministic
    # apart from the uuid, so there is no reason to assert anything less than the output.
    links = find_robust_links(a)
    assert len(links) == 1 and links[0].href == "B.md" and links[0].text == ""
    assert a == f"see ![](B.md) <!-- uuid: {EXISTING} --> here\n", f"unexpected rewrite: {a!r}"


def test_write_leaves_any_pandoc_attribute_suffix_untouched(tmp_path):
    """The suffix must stay OUT of the match span, and only a write can prove it.

    #52 blamed `{width="…"}` for hiding the link. The fix must not "help" by consuming the suffix:
    a regex ending `\\)(?:\\{[^}]*\\})?` passes every *detection* test in the suite while `--write`
    silently **deletes the attributes** from the document. Detection reports an identical finding
    either way, so this is the only place the difference is observable.

    Every attribute shape pandoc emits is covered, not just the one from the bug report. A version
    of this test that used `{width="…"}` alone was defeated by a seed one character narrower —
    `\\)(?:\\{\\.[^}]*\\})?`, which consumes only class blocks — passing the whole suite while destroying
    `{.cls}`. That shape is the very one used as the example in issue #65 and in the spec. A test
    fixture is a claim about a population, and a single sample is the weakest possible one.
    """
    shapes = ['{width="1.1in" height="2in"}', "{.cls}", "{#anchor}", '{.a .b key="v"}']
    # Vary the LINK TEXT as well as the attribute shape. A version of this test that used an empty
    # alt throughout was defeated by a seed that ate the block only when the text is non-empty —
    # the whole suite green while `![alt text](B.md){width=…}` lost its attributes. The text is the axis
    # this whole feature is about, so it is the last one that should have been held constant.
    texts = ["", "alt text", "x"]
    _w(tmp_path / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    cases = [(t, s) for t in texts for s in shapes]
    for i, (text, suffix) in enumerate(cases):
        _w(tmp_path / f"A{i}.md", f"![{text}](B.md){suffix}\n")

    apply_robustify(plan_robustify(tmp_path))

    for i, (text, suffix) in enumerate(cases):
        a = (tmp_path / f"A{i}.md").read_text()
        assert suffix in a, f"attribute block {suffix!r} was eaten after text {text!r}: {a!r}"


def test_repair_write_leaves_a_pandoc_attribute_suffix_untouched(tmp_path):
    """`ROBUST_LINK_RE` widened too, and it has its OWN write path: `repair`.

    Two regexes were widened and two write paths exist, but only `robustify`'s was guarded. This
    pins that `repair` rewrites the href and leaves everything after the anchor byte-for-byte —
    a splice whose end offset is one character off deletes the `{`, and the block stops being a
    block. The shape where the attributes sit *before* the anchor is the sibling test below; the
    two seeds are different and neither test catches the other's.

    This is the shape darnlink itself wrote BEFORE #65 was fixed (attrs after the anchor — the bug
    itself), not the shape it writes now. Kept as a repair test on purpose: files anchored by an
    older darnlink can still be sitting in a repo, and `repair` must not corrupt them just because
    it no longer produces this shape. `ROBUST_LINK_RE` still matches only the LINK+comment part of
    this string (its `attrs` group is empty here, since nothing but whitespace follows `)`), so the
    trailing `{width="1.1in"}` sits entirely outside the match and is never part of what gets spliced.
    """
    from darnlink.frontmatter_index import build_index
    from darnlink.repair import plan_repairs, apply_repairs

    _w(tmp_path / "new" / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    _w(tmp_path / "A.md", f'![](old/B.md) <!-- uuid: {EXISTING} -->{{width="1.1in"}}\n')

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))

    # Assert the whole line. `'width="1.1in"' in a` is satisfied by `…-->width="1.1in"}` — the
    # brace eaten and the block silently demoted to prose — which is exactly the splice-off-by-one
    # this test exists to catch. Its sibling asserts `== original` for the same reason.
    a = (tmp_path / "A.md").read_text()
    assert a == f'![](new/B.md) <!-- uuid: {EXISTING} -->{{width="1.1in"}}\n', f"bad rewrite: {a!r}"


def test_an_attribute_block_before_the_anchor_IS_a_robust_link(tmp_path):
    """FR-065: `![](x){.cls} <!-- uuid: … -->` is the CORRECT shape, and `repair` must heal it.

    Before #65 was fixed, `ROBUST_LINK_RE` required only whitespace between `)` and the comment, so
    this exact shape was refused robust status — a deliberate restriction, guarding a real bug: an
    earlier, narrower widening (an `attrs` group added to the regex with nothing carrying it through
    to the rewrite) made `repair --write` recognise the link and then silently DELETE the block while
    rewriting the href, because nothing told `emit_robust_link` the block existed.

    #65's fix widens the SAME regex, but pins `attrs` as its own group and threads it through
    `RobustLink.attrs` -> `emit_robust_link(..., attrs)` in both write paths (`repair`, `robustify`).
    So recognising this shape is safe now for a reason the old test could not rely on: the deletion
    bug is fixed at its actual cause (attrs never carried), not avoided by refusing to look.

    This is exactly the scenario #65 exists for: a moved target, an attrs block that must stay
    immediately after `)` for pandoc to honour it, and a `repair` that must do both at once.
    """
    from darnlink.frontmatter_index import build_index
    from darnlink.repair import plan_repairs, apply_repairs

    _w(tmp_path / "new" / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    original = f'![](old/B.md){{width="1.1in"}} <!-- uuid: {EXISTING} -->\n'
    _w(tmp_path / "A.md", original)

    links = find_robust_links(original)
    assert len(links) == 1 and links[0].attrs == '{width="1.1in"}', links

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))

    a = (tmp_path / "A.md").read_text()
    assert a == f'![](new/B.md){{width="1.1in"}} <!-- uuid: {EXISTING} -->\n', f"bad rewrite: {a!r}"


def test_absorbing_a_stray_anchor_does_not_eat_an_attribute_block(tmp_path):
    """The one place `robustify` DELETES text, guarded where the two features meet.

    `![](B.md){.cls} <!-- uuid: X -->` is itself a robust link since #65 (sibling test above), so it
    can no longer drive this test: `find_plain_links` now skips PAST the `{.cls}` before checking
    for a trailing anchor, sees one, and treats the link as already robust — nothing is plain, the
    absorb path never runs, and the fixture would silently stop testing anything.

    What still reaches the absorb path with an attrs block in front of it is a link whose trailing
    anchor is detached by something ELSE besides the attrs — prose between the attrs and the comment
    is enough, since `_TRAILING_UUID_RE` demands the comment immediately (only whitespace) after
    whatever `_skip_attrs` walked past.

    When a link is followed by a stray uuid comment, robustify absorbs it: it removes the stray and
    re-emits the link anchored (attrs included, right after `)`, per FR-065). Removing means walking
    back over the whitespace before the comment — and a boundary that also walks over `}` eats the
    closing brace of the attribute block, leaving `…{.cls` : the block silently becomes prose. That
    is the corruption this test exists to catch; asserting the whole line is what catches it (a
    boundary one character short leaves a trailing space, one character long eats a real character —
    `"{.cls}" in a` alone would miss both).
    """
    _w(tmp_path / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    _w(tmp_path / "A.md", f"![](B.md){{.cls}} **stuff** <!-- uuid: {EXISTING} -->\n")

    apply_robustify(plan_robustify(tmp_path))

    a = (tmp_path / "A.md").read_text()
    assert a == f"![](B.md){{.cls}} <!-- uuid: {EXISTING} --> **stuff**\n", f"bad rewrite: {a!r}"


def test_absorbing_a_stray_does_not_eat_a_closing_paren_of_prose(tmp_path):
    """Same deletion boundary, the other character it could walk back over.

    `(see [x](B.md)) <!-- uuid: X -->` — the comment follows the *parenthetical's* `)`, not the
    link's, so it is a stray and the absorb path runs. A boundary that walks back over `)` as well
    as whitespace deletes a character of the author's prose and leaves `(see [x](B.md)` unbalanced.

    The sibling fixture cannot reach this: its attribute block sits between the link and the space,
    so no `)` is ever adjacent to the boundary. One shape per character the walk-back could eat.
    """
    _w(tmp_path / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    _w(tmp_path / "A.md", f"(see [x](B.md)) <!-- uuid: {EXISTING} -->\n")

    apply_robustify(plan_robustify(tmp_path))

    a = (tmp_path / "A.md").read_text()
    assert a == f"(see [x](B.md) <!-- uuid: {EXISTING} -->)\n", f"bad rewrite: {a!r}"


def test_repair_finds_a_robust_link_whose_destination_has_parens(tmp_path):
    """`ROBUST_LINK_RE` widened too, and reverting that half alone left the whole suite green.

    Real damage under that revert: an anchored link whose destination carries balanced parentheses
    is not recognised as robust at all, so when its target moves `repair` returns **no finding** —
    the stale path survives and the gate stays green. The coupling is the same one FR-051
    established; what was missing was a test that fails when it is broken.
    """
    from darnlink.frontmatter_index import build_index
    from darnlink.repair import plan_repairs, apply_repairs

    _w(tmp_path / "new" / "a(b).md", f"---\nuuid: {EXISTING}\n---\n# a\n")
    _w(tmp_path / "A.md", f"see [r](old/a(b).md) <!-- uuid: {EXISTING} -->\n")

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))

    a = (tmp_path / "A.md").read_text()
    assert "new/a(b).md" in a, f"repair did not see the parenthesised robust link: {a!r}"


def test_65_the_reported_example_anchors_with_attrs_in_place(tmp_path):
    """The exact reproduction from #65, run through `--write` end to end.

    `![](B.md){width="1.1in" height="2in"}` anchored by `robustify` used to become
    `![](B.md) <!-- uuid: … -->{width="1.1in" height="2in"}` — the comment landing BETWEEN the link
    and its attributes, which pandoc requires immediately after `)`. The block still renders (as
    plain text, ignored), so the corruption is silent: nothing about the finding, the exit code, or
    a diff review flags it. This is the case that motivated the fix; the other tests in this file
    guard the mechanism, this one guards the actual bug report.
    """
    _w(tmp_path / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    _w(tmp_path / "A.md", '![](B.md){width="1.1in" height="2in"}\n')

    apply_robustify(plan_robustify(tmp_path))

    a = (tmp_path / "A.md").read_text()
    assert a == f'![](B.md){{width="1.1in" height="2in"}} <!-- uuid: {EXISTING} -->\n', f"bad rewrite: {a!r}"


def test_65_a_second_pass_over_an_attrs_anchored_link_is_a_no_op(tmp_path):
    """The regression `_TRAILING_UUID_RE`'s own docstring warned about: seen, not just claimed.

    `find_plain_links` must skip PAST an attrs block before checking for a trailing anchor comment,
    or a link this same tool just anchored reads as plain again next run and gets a SECOND `<!-- uuid
    -->` appended — the uuid twice in one file, one copy anchoring nothing, and the tree still
    reports clean because the link is (trivially) robust either way. Two full passes, not one: a
    fixture that starts already-anchored would not catch a version of this bug that only manifests
    on the SECOND write.
    """
    _w(tmp_path / "B.md", f"---\nuuid: {EXISTING}\n---\n# B\n")
    _w(tmp_path / "A.md", '![](B.md){.cls}\n')

    apply_robustify(plan_robustify(tmp_path))
    once = (tmp_path / "A.md").read_text()
    apply_robustify(plan_robustify(tmp_path))
    twice = (tmp_path / "A.md").read_text()

    assert once == twice, f"not idempotent: {once!r} -> {twice!r}"
    assert twice.count(EXISTING) == 1, f"uuid duplicated: {twice!r}"
