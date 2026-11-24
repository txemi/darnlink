"""#74: link destinations with parentheses (and spaces) are read whole, and `--write` keeps their form.

A folder named `Foo (Bar)` is ordinary in documents exported from other systems, and a README links
to it in one of five spellings. Before the link scanner, every one of them was cut at the first `)`
(or, for `%28`, never anchored), so the gate reported dead links to folders that were on disk and
`--write` rewrote them into links that were broken for real. These tests pin, for each spelling:
it validates, robustify anchors it without touching the destination, and repair after a move
writes the new path in the same spelling, which then validates again.
"""
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

from darnlink.cli import main
from darnlink.frontmatter_index import build_index
from darnlink.links import find_plain_links, find_robust_links, scan_links, spell_destination
from darnlink.paths import destination_path
from darnlink.repair import apply_repairs, plan_repairs
from darnlink.report import Kind
from darnlink.robustify import apply_robustify, plan_robustify

U_DOC = "aaaaaaaa-0000-0000-0000-000000000001"
U_DIR = "aaaaaaaa-0000-0000-0000-000000000002"
U_NOTE = "aaaaaaaa-0000-0000-0000-000000000003"
U_Q = "aaaaaaaa-0000-0000-0000-000000000004"
U_NEST = "aaaaaaaa-0000-0000-0000-000000000005"

#: (name, link as written, uuid it anchors to). Every destination denotes a file or folder below.
FORMS = [
    ("raw balanced", "[q](Q(1)/)", U_Q),
    ("raw with space", "[d](Foo (Bar)/)", U_DIR),
    ("escaped", r"[d](Foo \(Bar\)/)", U_DIR),
    ("angle", "[d](<Foo (Bar)/>)", U_DIR),
    ("percent", "[d](Foo%20%28Bar%29/)", U_DIR),
    ("nested", "[n](n(a(b))c.md)", U_NEST),
    ("title", '[t](<Foo (Bar)/note.md> "A (title)")', U_NOTE),
    ("bare with title", "[t](n(a(b))c.md 'title')", U_NEST),
]


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _tree(root: Path, body: str) -> Path:
    _w(root / "Foo (Bar)" / "README.md", f"---\nuuid: {U_DIR}\n---\n# Foo (Bar)\n")
    _w(root / "Foo (Bar)" / "note.md", f"---\nuuid: {U_NOTE}\n---\n# note\n")
    _w(root / "Q(1)" / "README.md", f"---\nuuid: {U_Q}\n---\n# Q\n")
    _w(root / "n(a(b))c.md", f"---\nuuid: {U_NEST}\n---\n# nested\n")
    doc = root / "doc.md"
    _w(doc, f"---\nuuid: {U_DOC}\n---\n\n{body}\n")
    return doc


def _kinds(result, kind):
    return [f for f in result.findings if f.kind is kind]


# --- The scanner ----------------------------------------------------------------------------------

@pytest.mark.parametrize("src, href, angle", [
    ("[x](../A (Z)/)", "../A (Z)/", False),
    (r"[x](../A \(Z\)/)", r"../A \(Z\)/", False),
    ("[x](<../A (Z)/>)", "../A (Z)/", True),
    ("[x](../A%20%28Z%29/)", "../A%20%28Z%29/", False),
    ("[x](a(b(c(d)))e.md)", "a(b(c(d)))e.md", False),
    ('[x](a.md "title")', "a.md", False),
    ("[x](a.md (title))", "a.md", False),
    ("[x]( a.md )", "a.md", False),
    ("[x](<a b.md> 'title')", "a b.md", True),
])
def test_the_destination_is_read_whole(src, href, angle):
    (m,) = list(scan_links(src))
    assert (m.href, m.angle, m.end) == (href, angle, len(src))


def test_strict_commonmark_wins_where_it_applies():
    """`[x](../A (Z))` IS a CommonMark link: destination `../A`, title `Z`. The spaced rung only
    applies where CommonMark says "not a link", so this is read as every renderer reads it."""
    (m,) = list(scan_links("[x](../A (Z))"))
    assert m.href == "../A"


def test_an_unbalanced_paren_does_not_swallow_the_neighbouring_link():
    """Neither the CommonMark rung (unbalanced) nor the spaced rung (it holds a `[`) can take the
    span, so the old truncating fallback reports the broken link and the next one survives."""
    hrefs = [m.href for m in scan_links("[a](x(y.md) and [b](t.md) [c](u(v.md)")]
    assert hrefs == ["x(y.md", "t.md", "u(v.md"]


def test_the_spaced_rung_never_crosses_a_line():
    hrefs = [m.href for m in scan_links("[a](x (y)\n[b](t.md)\n")]
    assert "t.md" in hrefs


@pytest.mark.parametrize("spelled, path", [
    (r"Foo \(Bar\)/", "Foo (Bar)/"),
    ("Foo%20%28Bar%29/", "Foo (Bar)/"),
    (r"a\b\(c", r"a\b(c"),           # a backslash before a letter is a literal backslash
])
def test_destination_path_undoes_escapes_and_percent(spelled, path):
    assert destination_path(spelled) == path


# --- Validation: every spelling resolves, and robustify writes it back untouched --------------------

@pytest.mark.parametrize("name, link, uuid", FORMS, ids=[f[0] for f in FORMS])
def test_each_form_validates_and_robustify_keeps_it_byte_for_byte(tmp_path, name, link, uuid):
    doc = _tree(tmp_path, link)
    result = plan_robustify(tmp_path)
    assert _kinds(result, Kind.DANGLING) == [], result.findings
    assert len(_kinds(result, Kind.ROBUSTIFY)) == 1, result.findings
    apply_robustify(result)
    assert doc.read_text(encoding="utf-8").endswith(f"\n{link} <!-- uuid: {uuid} -->\n")

    # Round trip: the written link is robust, and `check`/`repair` find nothing to do with it.
    (robust,) = find_robust_links(doc.read_text(encoding="utf-8"))
    assert robust.uuid == uuid
    assert plan_repairs(tmp_path, build_index(tmp_path)).findings == []
    again = plan_robustify(tmp_path)
    assert again.new_content == {} and _kinds(again, Kind.DANGLING) == []


def test_a_dead_destination_with_parens_is_reported_whole(tmp_path):
    """Widening the grammar must not hide a genuinely dead link of the same shape, and the report
    names the path it denotes, not a truncated one."""
    _tree(tmp_path, r"[g](Gone \(Bar\)/x.md) [h](<Gone (Bar)/y.md>)")
    found = _kinds(plan_robustify(tmp_path), Kind.DANGLING)
    assert len(found) == 2
    assert "Gone (Bar)/x.md" in found[0].detail and "Gone (Bar)/y.md" in found[1].detail


# --- Repair after a move: the new path is written in the author's spelling ------------------------

@pytest.mark.parametrize("before, after", [
    ("[t](Foo (Bar)/note.md)", "[t](Baz (Qux)/note.md)"),
    (r"[t](Foo \(Bar\)/note.md)", r"[t](Baz \(Qux\)/note.md)"),
    ("[t](<Foo (Bar)/note.md>)", "[t](<Baz (Qux)/note.md>)"),
    ("[t](Foo%20%28Bar%29/note.md)", "[t](Baz%20%28Qux%29/note.md)"),
    ('[t](<Foo (Bar)/note.md> "A (title)")', '[t](<Baz (Qux)/note.md> "A (title)")'),
    ("[t](Foo%20%28Bar%29/note.md#part)", "[t](Baz%20%28Qux%29/note.md#part)"),
], ids=["raw space", "escaped", "angle", "percent", "title", "percent with fragment"])
def test_repair_after_a_move_keeps_the_form(tmp_path, before, after):
    doc = _tree(tmp_path, f"{before} <!-- uuid: {U_NOTE} -->")
    (tmp_path / "Foo (Bar)").rename(tmp_path / "Baz (Qux)")

    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert len(_kinds(result, Kind.REPAIR)) == 1, result.findings
    apply_repairs(result)
    assert doc.read_text(encoding="utf-8").endswith(f"\n{after} <!-- uuid: {U_NOTE} -->\n")
    # Round trip: what was written resolves, so a second pass is clean.
    assert plan_repairs(tmp_path, build_index(tmp_path)).findings == []
    assert _kinds(plan_robustify(tmp_path), Kind.DANGLING) == []


def test_repair_switches_to_angle_brackets_only_when_a_space_appears(tmp_path):
    """A bare destination with no space, whose target moves INTO a folder named with a space: a raw
    space would make the link plain text on every CommonMark renderer, so it becomes `<…>`. That
    is the one change of form `--write` makes, and only when it is necessary."""
    _w(tmp_path / "plain" / "note.md", f"---\nuuid: {U_NOTE}\n---\n# note\n")
    doc = tmp_path / "doc.md"
    _w(doc, f"[t](plain/note.md) <!-- uuid: {U_NOTE} -->\n")
    (tmp_path / "Baz (Qux)").mkdir()
    (tmp_path / "plain" / "note.md").rename(tmp_path / "Baz (Qux)" / "note.md")

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))
    assert doc.read_text(encoding="utf-8") == f"[t](<Baz (Qux)/note.md>) <!-- uuid: {U_NOTE} -->\n"
    assert plan_repairs(tmp_path, build_index(tmp_path)).findings == []


def test_repair_into_balanced_parens_without_a_space_stays_raw(tmp_path):
    _w(tmp_path / "plain" / "note.md", f"---\nuuid: {U_NOTE}\n---\n# note\n")
    doc = tmp_path / "doc.md"
    _w(doc, f"[t](plain/note.md) <!-- uuid: {U_NOTE} -->\n")
    (tmp_path / "Q(1)").mkdir()
    (tmp_path / "plain" / "note.md").rename(tmp_path / "Q(1)" / "note.md")

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))
    assert doc.read_text(encoding="utf-8") == f"[t](Q(1)/note.md) <!-- uuid: {U_NOTE} -->\n"


@pytest.mark.parametrize("path, old, angle, want", [
    ("x(y.md", "a.md", False, "<x(y.md>"),                 # unbalanced: never left to rung 3
    ("100%41.md", "a.md", False, "100%2541.md"),           # a literal `%XX` in a file name
    ("100%41 x.md", "a.md", False, "<100%2541 x.md>"),
    ("a<b>.md", "x.md", True, r"<a\<b\>.md>"),
    ("Q(1)/x.md", "a%20b.md", False, "Q%281%29/x.md"),
])
def test_spell_destination_edge_cases(path, old, angle, want):
    assert spell_destination(path, "", old, angle) == want


# --- The same through the command line -------------------------------------------------------------

def test_cli_write_round_trip(tmp_path, capsys):
    doc = _tree(tmp_path, "\n".join(f[1] for f in FORMS))
    assert main([str(tmp_path), "--robustify", "--write"]) == 0
    text = doc.read_text(encoding="utf-8")
    for _, link, uuid in FORMS:
        assert f"{link} <!-- uuid: {uuid} -->" in text, link
    assert main(["check", str(tmp_path)]) == 0
    capsys.readouterr()


def test_a_web_link_keeps_its_title_and_brackets_in_the_listing_and_the_write():
    from darnlink.weblinks import find_web_links
    src = '[w](<https://github.com/o/r/blob/main/a.md> "T")'
    (link,) = find_web_links(src)
    assert link.href == "https://github.com/o/r/blob/main/a.md"
    assert link.inner == '<https://github.com/o/r/blob/main/a.md> "T"'


def test_plain_and_robust_partitions_agree():
    src = f"[a](<x y.md>) [b](Foo (Bar)/) <!-- uuid: {U_DIR} --> [c](z.md)"
    assert [p.href for p in find_plain_links(src)] == ["x y.md", "z.md"]
    assert [(r.href, r.uuid) for r in find_robust_links(src)] == [("Foo (Bar)/", U_DIR)]


# --- Review round 1 of #74 -------------------------------------------------------------------------

@pytest.mark.parametrize("href, local", [
    ("%2Fetc%2Fx.md", False),          # encoded absolute path
    (r"\/etc/x.md", False),            # escaped absolute path
    ("http%3A//example.com/x", False),  # encoded scheme
    ("a%2Fb.md", True),                # an encoded `/` inside a relative path is still relative
    (r"Foo \(Bar\)/", True),
])
def test_is_local_relative_judges_the_decoded_spelling(href, local):
    from darnlink.paths import is_local_relative
    assert is_local_relative(href) is local


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX absolute paths")
@pytest.mark.parametrize("spell", ["encoded", "escaped"])
@pytest.mark.parametrize("where", ["inside", "outside"])
def test_an_encoded_or_escaped_absolute_path_is_never_anchored(tmp_path, spell, where):
    """Decoding must not turn `%2Fhome%2F…` or `\\/home/…` into a local target: joined onto the
    linking directory, an absolute path drops that directory, so the link would resolve to the real
    file and be anchored -- a false green. It is an absolute local path, inside the root or not."""
    root = tmp_path / "root"
    target = (root / "b.md") if where == "inside" else (tmp_path / "out" / "o.md")
    _w(target, f"---\nuuid: {U_NOTE}\n---\n# b\n")
    href = quote(str(target), safe="") if spell == "encoded" else "\\" + str(target)
    doc = root / "doc.md"
    _w(doc, f"---\nuuid: {U_DOC}\n---\n\n[x]({href})\n")

    result = plan_robustify(root)
    kinds = {f.kind for f in result.findings if f.file == doc}
    assert Kind.ABSOLUTE_LOCAL_PATH in kinds, result.findings
    assert not kinds & {Kind.ROBUSTIFY, Kind.OUT_OF_SCOPE, Kind.DANGLING}, result.findings
    assert doc not in result.new_content


def test_repair_into_a_folder_with_a_hash_encodes_it(tmp_path):
    """`#` in a new path would start the fragment: `<C#/note.md>` reads back as `C`, and the next
    pass reports a false CONFLICT. It is written `%23` in the raw and `<…>` forms alike."""
    _w(tmp_path / "old" / "note.md", f"---\nuuid: {U_NOTE}\n---\n# note\n")
    doc = tmp_path / "doc.md"
    _w(doc, f"[a](old/note.md) <!-- uuid: {U_NOTE} -->\n[b](<old/note.md#part>) <!-- uuid: {U_NOTE} -->\n")
    (tmp_path / "C#").mkdir()
    (tmp_path / "old" / "note.md").rename(tmp_path / "C#" / "note.md")

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))
    assert doc.read_text(encoding="utf-8") == (f"[a](C%23/note.md) <!-- uuid: {U_NOTE} -->\n"
                                               f"[b](<C%23/note.md#part>) <!-- uuid: {U_NOTE} -->\n")
    assert plan_repairs(tmp_path, build_index(tmp_path)).findings == []


@pytest.mark.parametrize("path, angle, want", [
    ("C#/n.md", False, "C%23/n.md#f"),
    ("C#/n.md", True, "<C%23/n.md#f>"),
    ("what?/n.md", False, "what%3F/n.md#f"),
])
def test_spell_destination_encodes_what_a_url_reader_would_cut(path, angle, want):
    assert spell_destination(path, "f", "old.md", angle) == want


def test_a_yaml_link_is_resolved_literally(tmp_path):
    """Decision (#74): the Markdown reading (escapes, `%XX`) is for link destinations only. A YAML
    `link:` is a plain path value, so `a%20b.md` does not name `a b.md` there: it still needs a
    repair, exactly as before."""
    from darnlink import yaml_refs
    from darnlink.frontmatter_index import DEFAULT_EXCLUDES
    _w(tmp_path / "a b.md", f"---\nuuid: {U_NOTE}\n---\n")
    y = tmp_path / "x.yaml"
    _w(y, "")
    index = yaml_refs.build_target_index(tmp_path, set(DEFAULT_EXCLUDES), {})
    judged = {link: yaml_refs.judge({"link": link, "uuid": U_NOTE}, y, index, tmp_path)[0]
              for link in ("a%20b.md", "a b.md")}
    assert judged == {"a%20b.md": yaml_refs.REPAIR, "a b.md": yaml_refs.OK}


@pytest.mark.parametrize("src, hrefs", [
    ('[y](Foo (Bar)/ "T")', ["Foo (Bar)/"]),
    ("[y](Foo (Bar)/ 'T') [z](q.md)", ["Foo (Bar)/", "q.md"]),
    ("[y](John's notes/x.md)", ["John's notes/x.md"]),
    ('[y](a b/ "T [z](q.md)")', ['a b/ "T [z](q.md']),   # a title may not hold `[`: old fallback
])
def test_the_spaced_form_accepts_a_trailing_title(src, hrefs):
    assert [m.href for m in scan_links(src)] == hrefs


def test_repair_of_a_spaced_link_with_a_title(tmp_path):
    """Without title support the href read `old dir/note.md "T"`: not a `.md` name, so repair took
    it for a directory link and reported a false CONFLICT after a move."""
    _w(tmp_path / "old dir" / "note.md", f"---\nuuid: {U_NOTE}\n---\n# note\n")
    doc = tmp_path / "doc.md"
    _w(doc, f'[t](old dir/note.md "T") <!-- uuid: {U_NOTE} -->\n')
    (tmp_path / "new dir").mkdir()
    (tmp_path / "old dir" / "note.md").rename(tmp_path / "new dir" / "note.md")

    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert [f.kind for f in result.findings] == [Kind.REPAIR], result.findings
    apply_repairs(result)
    assert doc.read_text(encoding="utf-8") == f'[t](new dir/note.md "T") <!-- uuid: {U_NOTE} -->\n'


# --- Review round 2 of #74 -------------------------------------------------------------------------

#: Inputs the pre-scanner regex, or an earlier scanner, read in quadratic time. Each one, at this
#: size, took from seconds to minutes there; linear, it takes well under a second. The bound is
#: deliberately loose so a slow machine does not fail it, and still far below quadratic.
_QUADRATIC_BEFORE = {
    "unclosed bare": lambda n: "[a](b" * n,                   # no `)` anywhere
    "unclosed with paren": lambda n: "[a](b(" * n,
    "empty destinations": lambda n: "[a](" * n,
    "closing paren far away": lambda n: "[a](b(c)" * n + ")",
    "spaced, unclosed": lambda n: "[a](x y " * n,
    "a run of [ before one ]()": lambda n: "[" * n + "]()",
}


@pytest.mark.parametrize("name", list(_QUADRATIC_BEFORE))
def test_the_scan_is_linear_on_input_that_used_to_be_quadratic(name):
    import time
    text = _QUADRATIC_BEFORE[name](20000)
    t0 = time.perf_counter()
    list(scan_links(text))
    assert time.perf_counter() - t0 < 10, f"{name}: the scan is no longer linear"


def test_a_run_of_brackets_sharing_one_close_is_tried_once(monkeypatch):
    """Every `[` before the same `]` has the same destination, so only the first is tried. Counted,
    not timed: removing the skip leaves the output identical and costs one attempt per `[`."""
    import darnlink.links as links
    calls = []
    real = links._scan_commonmark
    monkeypatch.setattr(links, "_scan_commonmark", lambda s, p, n: calls.append(p) or real(s, p, n))
    assert list(links.scan_links("[" * 1000 + "]() x)")) == []
    assert len(calls) == 1, len(calls)


def test_nothing_is_tried_past_the_last_closing_paren(monkeypatch):
    """Every rung needs a `)`, so after the last one in the file no destination is even attempted.
    Counted, not timed (each attempt is cheap, the total is what stops being linear)."""
    import darnlink.links as links
    calls = []
    real = links._scan_commonmark
    monkeypatch.setattr(links, "_scan_commonmark", lambda s, p, n: calls.append(p) or real(s, p, n))
    assert [m.href for m in links.scan_links("[a](b) " + "[a](b" * 1000)] == ["b"]
    assert len(calls) == 1, len(calls)


def test_nesting_past_the_cmark_bound_falls_to_the_spaced_rung():
    """Rung 1 caps nesting at 32 levels, as cmark does; a deeper single-line destination is still
    read whole, by rung 2."""
    deep = "(" * 40 + "x" + ")" * 40
    (m,) = list(scan_links(f"[r](a{deep}.md)"))
    assert m.href == f"a{deep}.md"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX absolute paths")
def test_a_robust_link_with_an_encoded_absolute_path_is_repaired_not_trusted(tmp_path):
    """`resolve_href` keeps the literal spelling when decoding would make the href absolute. Without
    that guard, `%2F…%2Fb.md` would resolve to the real `b.md` and the link would pass as already
    correct, although it only works on the machine that wrote it."""
    _w(tmp_path / "b.md", f"---\nuuid: {U_NOTE}\n---\n# b\n")
    doc = tmp_path / "doc.md"
    _w(doc, f"[x]({quote(str(tmp_path / 'b.md'), safe='')}) <!-- uuid: {U_NOTE} -->\n")

    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert [f.kind for f in result.findings] == [Kind.REPAIR], result.findings
    apply_repairs(result)
    assert doc.read_text(encoding="utf-8") == f"[x](b.md) <!-- uuid: {U_NOTE} -->\n"


def test_a_new_path_that_would_read_as_path_plus_title_is_bracketed():
    """`A (Z)` written raw reads, in CommonMark, as `A` with the title `Z`: the read-back has to
    compare the decoded path, not just accept what the scanner returned."""
    assert spell_destination("A (Z)", "", "a.md", False) == "<A (Z)>"


def test_the_last_resort_encodes_the_fragment_too():
    from urllib.parse import unquote
    from darnlink.paths import split_fragment
    token = spell_destination("}\n[# ", "a)b", "x.md", False)
    (m,) = list(scan_links(f"[]({token})"))
    path, frag = split_fragment(m.href)
    assert (destination_path(path), unquote(frag)) == ("}\n[# ", "a)b")


def test_repair_drops_a_false_paren_title_that_is_part_of_the_folder_name(tmp_path):
    """`[x](Foo (Bar))` is `Foo` with the title `Bar` in CommonMark. With the folder `Foo (Bar)` in
    place and holding the uuid, repair rewrites the whole run, never `[x](<Foo (Bar)/> (Bar))`. In the
    same file, a link with a real title whose target moved keeps that title."""
    _tree(tmp_path, "")
    doc = tmp_path / "doc.md"
    _w(doc, f"[x](Foo (Bar)) <!-- uuid: {U_DIR} -->\n[y](gone.md (real title)) <!-- uuid: {U_NOTE} -->\n")

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))
    assert doc.read_text(encoding="utf-8") == (
        f"[x](<Foo (Bar)/>) <!-- uuid: {U_DIR} -->\n"
        f"[y](<Foo (Bar)/note.md> (real title)) <!-- uuid: {U_NOTE} -->\n")
    assert plan_repairs(tmp_path, build_index(tmp_path)).findings == []


def _folder_with_readme(root: Path, rel: str, uuid: str) -> None:
    _w(root / rel / "README.md", f"---\nuuid: {uuid}\n---\n# x\n")


def test_repair_drops_a_false_paren_title_after_the_folder_moved(tmp_path):
    """The folder `Foo (Bar)` moved to `sub/`: the longer reading no longer resolves, but its last
    component is the target's name, so the false title still goes with the rewrite."""
    _folder_with_readme(tmp_path, "sub/Foo (Bar)", U_DIR)
    doc = tmp_path / "docs" / "index.md"
    _w(doc, f"[x](../Foo (Bar)) <!-- uuid: {U_DIR} -->\n")

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))
    assert doc.read_text(encoding="utf-8") == f"[x](<../sub/Foo (Bar)/>) <!-- uuid: {U_DIR} -->\n"
    assert plan_repairs(tmp_path, build_index(tmp_path)).findings == []


@pytest.mark.parametrize("moved", [False, True])
def test_a_real_paren_title_is_never_read_as_a_path(tmp_path, moved):
    """`guide.md (Guide)` is not the name of the target `guide.md`: the title stays a title, whether
    the link is already correct or the file moved."""
    _w(tmp_path / ("other" if moved else "sub") / "guide.md", f"---\nuuid: {U_NOTE}\n---\n# g\n")
    doc = tmp_path / "docs" / "index.md"
    _w(doc, f"[x](../sub/guide.md (Guide)) <!-- uuid: {U_NOTE} -->\n")

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))
    want = "../other/guide.md" if moved else "../sub/guide.md"
    assert doc.read_text(encoding="utf-8") == f"[x]({want} (Guide)) <!-- uuid: {U_NOTE} -->\n"


def test_a_live_commonmark_target_is_a_conflict_not_a_false_title(tmp_path):
    """The file `Foo` exists and does not hold the uuid; the folder `Foo (Bar)` does. The CommonMark
    reading names a live, different target, so this is a path/uuid CONFLICT, left untouched, as it
    was before the widening existed. The longer reading is never used to talk past it."""
    _w(tmp_path / "Foo", "not a folder\n")
    _folder_with_readme(tmp_path, "Foo (Bar)", U_DIR)
    doc = tmp_path / "docs" / "index.md"
    original = f"[x](../Foo (Bar)) <!-- uuid: {U_DIR} -->\n"
    _w(doc, original)

    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert [f.kind for f in result.findings] == [Kind.CONFLICT], result.findings
    apply_repairs(result)
    assert doc.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("before, target, after", [
    ("../guide.md#intro (Intro)", "sub/guide.md", "../sub/guide.md#intro (Intro)"),
    ("../Foo/#s (Note)", "sub/Foo/README.md", "../sub/Foo/#s (Note)"),
], ids=["file with fragment", "folder with fragment"])
def test_a_title_after_a_fragment_is_never_read_as_a_path(tmp_path, before, target, after):
    """With a `#` in the destination, the extra text would extend the FRAGMENT, not the path, so it
    cannot be part of a folder name: the title is a title, and it survives the rewrite after a move.
    (Without this, `../guide.md#intro (Intro)` reads as path `../guide.md`, whose name is the
    target's, and the title was silently dropped.)"""
    _w(tmp_path / target, f"---\nuuid: {U_NOTE}\n---\n# t\n")
    doc = tmp_path / "docs" / "index.md"
    _w(doc, f"[x]({before}) <!-- uuid: {U_NOTE} -->\n")

    apply_repairs(plan_repairs(tmp_path, build_index(tmp_path)))
    assert doc.read_text(encoding="utf-8") == f"[x]({after}) <!-- uuid: {U_NOTE} -->\n"
    assert plan_repairs(tmp_path, build_index(tmp_path)).findings == []


@pytest.mark.parametrize("live", ["folder with another uuid", "plain file"])
def test_a_live_longer_reading_that_is_not_the_target_is_a_conflict(tmp_path, live):
    """`[x](../A (B))` with a folder `A (B)` at the root holding ANOTHER uuid (or a plain file
    `A (B)`), while the uuid lives in `sub/A (B)/`: the author's text names a live, different target,
    so it is a CONFLICT, left untouched, never a silent rewrite to `sub/`."""
    if live == "plain file":
        _w(tmp_path / "A (B)", "not a folder\n")
    else:
        _folder_with_readme(tmp_path, "A (B)", U_Q)
    _folder_with_readme(tmp_path, "sub/A (B)", U_DIR)
    doc = tmp_path / "docs" / "index.md"
    original = f"[x](../A (B)) <!-- uuid: {U_DIR} -->\n"
    _w(doc, original)

    result = plan_repairs(tmp_path, build_index(tmp_path))
    assert [f.kind for f in result.findings] == [Kind.CONFLICT], result.findings
    assert "../A (B)" in result.findings[0].detail
    apply_repairs(result)
    assert doc.read_text(encoding="utf-8") == original
