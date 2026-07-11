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
