from darnlink.links import (
    find_robust_links,
    find_plain_links,
    emit_robust_link,
    ignored_spans,
    code_spans,
    file_is_ignored,
)

U = "11111111-1111-1111-1111-111111111111"


def test_detects_robust_link():
    c = f"x [B](old/B.md) <!-- uuid: {U} --> y"
    links = find_robust_links(c)
    assert len(links) == 1
    assert links[0].text == "B"
    assert links[0].href == "old/B.md"
    assert links[0].uuid == U


def test_detects_robust_link_tolerant_whitespace():
    c = f"[B](b.md)   <!--  uuid:  {U}  --> z"
    links = find_robust_links(c)
    assert len(links) == 1 and links[0].uuid == U


def test_plain_links_exclude_robust():
    c = f"[plain](p.md) and [robust](r.md) <!-- uuid: {U} -->"
    plains = find_plain_links(c)
    hrefs = [p.href for p in plains]
    assert "p.md" in hrefs
    assert "r.md" not in hrefs  # robust one excluded


def test_emit_canonical_single_space():
    assert emit_robust_link("B", "new/B.md", U) == f"[B](new/B.md) <!-- uuid: {U} -->"


def test_ignore_generated_block():
    c = (
        "[real](r.md)\n"
        "<!-- autogrid-start -->\n"
        f"| path | [gen](gen.md) <!-- uuid: {U} --> |\n"
        "<!-- autogrid-end -->\n"
        "[also_real](r2.md)\n"
    )
    spans = ignored_spans(c, ["autogrid"])
    assert [p.href for p in find_plain_links(c, spans)] == ["r.md", "r2.md"]  # gen.md skipped
    assert find_robust_links(c, spans) == []  # the robust link inside the block is skipped too
    # without the ignore, the generated links ARE seen
    assert len(find_robust_links(c)) == 1


# --- 002: ignore links inside code (fenced & inline) ---

def test_code_spans_fenced_backticks():
    c = "before [a](a.md)\n```markdown\n[gen](gen.md)\n```\nafter [b](b.md)\n"
    spans = code_spans(c)
    fence_start = c.index("```")
    fence_end = c.index("```\nafter") + len("```\n")
    assert spans == [(fence_start, fence_end)]


def test_code_spans_inline():
    c = "see `[x](y.md)` here"
    spans = code_spans(c)
    assert spans == [(c.index("`"), c.rindex("`") + 1)]


def test_find_plain_links_skips_fenced_and_inline_code():
    c = (
        "real prose [P](p.md)\n"
        "```markdown\n"
        "[fenced](fenced.md)\n"
        "```\n"
        "inline `[inl](inl.md)` and another real [Q](q.md)\n"
    )
    spans = code_spans(c)
    hrefs = [p.href for p in find_plain_links(c, spans)]
    assert hrefs == ["p.md", "q.md"]  # fenced.md and inl.md are skipped


def test_find_robust_links_skips_fenced_example():
    c = f"```\n[t](old.md) <!-- uuid: {U} -->\n```\n[real](r.md) <!-- uuid: {U} -->\n"
    spans = code_spans(c)
    links = find_robust_links(c, spans)
    assert len(links) == 1 and links[0].href == "r.md"  # fenced robust example skipped


def test_inline_code_opener_does_not_pair_across_fence():
    # an unmatched backtick in prose must NOT pair with a backtick inside a later fenced block,
    # which would swallow a real link in between (regression: cross-fence inline pairing).
    c = (
        "a ` [real](real.md) text\n"  # stray single backtick, then a REAL prose link
        "```text\n"
        "x`y\n"                        # a single backtick INSIDE the fence
        "```\n"
    )
    spans = code_spans(c)
    hrefs = [p.href for p in find_plain_links(c, spans)]
    assert "real.md" in hrefs  # the real link is still seen (not over-ignored)


def test_code_spans_tilde_fence_and_unclosed():
    c = "x [a](a.md)\n~~~\n[g](g.md)\n"  # unclosed tilde fence -> to EOF
    spans = code_spans(c)
    assert spans == [(c.index("~~~"), len(c))]
    assert [p.href for p in find_plain_links(c, spans)] == ["a.md"]


# --- 003: per-file opt-out via <!-- darnlink-ignore-file --> ---

def test_file_is_ignored_detects_marker():
    assert file_is_ignored("# Title\n<!-- darnlink-ignore-file -->\nbody\n")
    assert file_is_ignored("<!--darnlink-ignore-file-->\n")          # no inner spaces
    assert file_is_ignored("<!--   darnlink-ignore-file   -->\n")    # extra spaces
    assert not file_is_ignored("# normal file\n[a](a.md)\n")


def test_file_is_ignored_marker_inside_code_does_not_count():
    # documenting the marker inside a code fence/inline must NOT opt the file out (composes with 002)
    fenced = "# Docs\n```\n<!-- darnlink-ignore-file -->\n```\n"
    inline = "Use `<!-- darnlink-ignore-file -->` to opt out.\n"
    assert not file_is_ignored(fenced)
    assert not file_is_ignored(inline)


def test_detects_a_robust_link_whose_text_is_empty():
    """FR-051: `ROBUST_LINK_RE` widens with `MD_LINK_RE`, and that coupling needs its own test.

    Reverting only the robust half leaves every dangling test green — measured — because those go
    through `find_plain_links`. If the two disagree, an anchored `[](x) <!-- uuid: … -->` is plain to
    one function and robust to the other: `find_plain_links` skips it (it sees the trailing anchor)
    while `find_robust_links` never sees it, so its uuid drops out of the repair axis entirely and
    a moved target stops being healed. That is a false green in `repair`, not in `dangling`.
    """
    c = f"x [](old/B.md) <!-- uuid: {U} --> y"
    links = find_robust_links(c)
    assert len(links) == 1
    assert links[0].text == "" and links[0].href == "old/B.md" and links[0].uuid == U


def test_an_empty_text_image_anchor_is_robust_not_plain():
    """The two finders must agree on the same input — the invariant the coupling exists to hold."""
    c = f"![](media/photo.jpg) <!-- uuid: {U} -->"
    assert len(find_robust_links(c)) == 1
    assert find_plain_links(c) == []


def test_emit_round_trips_an_empty_text_link():
    """`emit_robust_link("")` must produce a link the grammar reads back identically.

    Scope, stated because an earlier version of this test overreached: this is emit → parse for an
    empty text, nothing more. Whether a *rewrite* keeps the `!` of an embed is span arithmetic in
    `robustify`, which this never calls — it lives in
    `test_robustify.test_write_preserves_the_bang_of_an_image_embed`.
    """
    out = emit_robust_link("", "new/B.md", U)
    assert out.startswith("[](")
    back = find_robust_links(out)
    assert len(back) == 1 and back[0].href == "new/B.md" and back[0].text == ""
