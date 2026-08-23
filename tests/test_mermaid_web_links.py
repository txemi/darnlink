"""Feature 017: the READ axis can see the destinations carried by a diagram's `click` directives.

Written before the implementation (constitution, Principle V). Network is never touched: every
online test injects a fake fetcher, like feature 013's tests.

The three things these tests exist to prove, in order of how easy they are to get wrong:

1. **The seeded defect is caught.** A blind check and a working one produce identical output on a
   healthy tree -- which is exactly how this class of link went unwatched. So the fixture is broken
   on purpose, and the flag-off run is asserted alongside the flag-on run: if the two ever agree,
   the feature is not wired and a green suite is a false pass (SC-019).
2. **Nothing is ever written into a diagram.** The read axis is not read-only: in its writing mode
   it anchors a link with a trailing HTML comment. A diagram comments with `%%`, so an HTML comment
   there is a *node*, not a comment -- writing one corrupts the drawing (FR-060, SC-023).
3. **That protection does not live in the caller.** A rule the call site must remember is a rule
   that disappears the day someone adds a second call site -- which is how this feature came to
   exist in the first place.
"""
import hashlib
from pathlib import Path

import pytest

from darnlink.cli import main
from darnlink.links import code_spans, mermaid_click_destinations, mermaid_region_bodies
from darnlink.weblinks import (GithubUrl, WebLink, _classify, check_web_links_online,
                               find_mermaid_web_links, find_web_links)

UUID = "3f9c1a2b-4d5e-6f70-8192-a3b4c5d6e7f8"
OWNER, REPO = "example-org", "handbook"
LIVE = f"https://github.com/{OWNER}/{REPO}/blob/main/docs/alive.md"
DEAD = f"https://github.com/{OWNER}/{REPO}/blob/main/docs/moved-away.md"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _checksums(root: Path):
    return {p: hashlib.sha1(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*.md"))}


def _fetcher(responses):
    def f(gu: GithubUrl, token):
        return responses.get(f"https://github.com/{gu.owner}/{gu.repo}/blob/{gu.ref}/{gu.path}",
                             (404, None))
    return f


#: The fixture diagram. Four directives, and only ONE of them is a finding:
#: the control (live), the seeded defect (dead), a comment line that contains a whole directive,
#: and a callback binding that carries no destination at all.
DIAGRAM = f"""# A drawing

```mermaid
flowchart TD
  A["alive"] --> B["gone"]
  %% click Z href "{DEAD}" _blank   <- a comment, not a directive (FR-056)
  click A href "{LIVE}" _blank
  click B href "{DEAD}" _blank
  click A call showTooltip()
```

Ordinary prose after the drawing.
"""


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _w(root / "diagram.md", DIAGRAM)
    _w(root / "prose.md",
       "click the button, then read on. This paragraph starts with the directive word\n"
       "on purpose and lives outside every fence.\n")
    _w(root / "example.md",
       "Showing a diagram as an example:\n\n"
       "````markdown\n```mermaid\nflowchart TD\n"
       f'  click Q href "{DEAD}" _blank\n'
       "```\n````\n")
    _w(root / "unclosed.md",
       "# Never closed\n\n```mermaid\nflowchart TD\n"
       f'  click U href "{DEAD}" _blank\n')
    return root


# --------------------------------------------------------------------------------------------
# Phase B / T003-T004 -- regions and the recogniser, in isolation
# --------------------------------------------------------------------------------------------

def test_mermaid_regions_are_a_subset_of_code_regions():
    """The invariant that keeps FR-015 safe: everything this feature can see is something the
    write axis was already forbidden to touch. If this ever fails, a second notion of 'fenced
    block' has crept in (FR-054)."""
    content = DIAGRAM
    code = code_spans(content)
    for start, end in mermaid_region_bodies(content):
        assert any(cs <= start and end <= ce for cs, ce in code), \
            "a mermaid region escaped the code regions -- regions are being computed twice"


def test_only_mermaid_fences_count():
    content = "```python\nclick A href \"http://x/y\"\n```\n"
    assert mermaid_region_bodies(content) == []


def test_info_string_with_extra_words_is_still_mermaid():
    content = '```mermaid title="x"\nclick A href "http://x/y" _blank\n```\n'
    assert len(mermaid_region_bodies(content)) == 1


@pytest.mark.parametrize("line, expected", [
    ('  click A href "http://x/y" _blank', "http://x/y"),   # the 1961-occurrence shape
    ('  click A "http://x/y" _blank', "http://x/y"),        # the 147-occurrence shape
    ('  click A href "http://x/y"', "http://x/y"),          # the 57-occurrence shape
    ('  click A href "http://x/y" "a tooltip"', "http://x/y"),
])
def test_recogniser_accepts_the_three_measured_shapes(line, expected):
    content = f"```mermaid\nflowchart TD\n{line}\n```\n"
    assert [d for _, d in mermaid_click_destinations(content)] == [expected]


def test_recogniser_reports_absolute_offsets():
    """The offset must be into the FILE, not into the region body: the report points at a location
    a human has to be able to find."""
    content = DIAGRAM
    for offset, dest in mermaid_click_destinations(content):
        assert content[offset:offset + 5] == "click"
        assert dest in content


# --------------------------------------------------------------------------------------------
# Phase D / T011-T014 -- precision. These are the ones that decide whether the gate gets trusted
# --------------------------------------------------------------------------------------------

def test_comment_line_carrying_a_directive_yields_nothing():
    """Not hypothetical: a real tree contains a diagram comment whose prose includes the directive
    word (FR-056)."""
    content = f'```mermaid\nflowchart TD\n  %% click Z href "{DEAD}" _blank\n```\n'
    assert mermaid_click_destinations(content) == []


def test_callback_binding_yields_nothing():
    content = "```mermaid\nflowchart TD\n  click A call showTooltip()\n  click B callback\n```\n"
    assert mermaid_click_destinations(content) == []


def test_the_fixture_diagram_yields_exactly_two_destinations():
    """Four directives in the drawing; the comment and the callback are not destinations."""
    got = sorted(d for _, d in mermaid_click_destinations(DIAGRAM))
    assert got == sorted([LIVE, DEAD])


def test_prose_beginning_with_the_directive_word_is_unreachable(tmp_path):
    prose = (tmp_path / "prose.md")
    _w(prose, "click the button and carry on\n")
    assert mermaid_click_destinations(prose.read_text()) == []


def test_a_diagram_shown_as_an_example_is_never_scanned(tmp_path):
    """The outer fence wins -- inherited from FR-016, asserted here so a reimplementation would
    be caught."""
    content = (tmp_path / "example.md")
    _w(content, "````markdown\n```mermaid\nflowchart TD\n"
                f'  click Q href "{DEAD}" _blank\n```\n````\n')
    assert mermaid_click_destinations(content.read_text()) == []


def test_unclosed_fence_runs_to_eof():
    content = f'# t\n\n```mermaid\nflowchart TD\n  click U href "{LIVE}" _blank\n'
    assert [d for _, d in mermaid_click_destinations(content)] == [LIVE]


def test_tilde_fence_behaves_like_a_backtick_fence():
    content = f'~~~mermaid\nflowchart TD\n  click U href "{LIVE}" _blank\n~~~\n'
    assert [d for _, d in mermaid_click_destinations(content)] == [LIVE]


# --------------------------------------------------------------------------------------------
# T015-T018 -- report-only: the property, not the flag
# --------------------------------------------------------------------------------------------

def test_recognised_items_are_report_only():
    for link in find_mermaid_web_links(DIAGRAM):
        assert link.report_only is True


def test_ordinary_web_links_are_not_report_only():
    content = f"A prose link: [alive]({LIVE})\n"
    for link in find_web_links(content):
        assert link.report_only is False


def test_report_only_survives_the_union():
    """The union is where a property is most easily dropped: two lists merged, one of them losing
    what made it special."""
    content = DIAGRAM + f"\nAnd a prose link: [alive]({LIVE})\n"
    links = find_web_links(content, code_spans(content), include_mermaid=True)
    by_flag = {}
    for link in links:
        by_flag.setdefault(link.report_only, []).append(link)
    assert by_flag.get(True), "the diagram destinations lost their property in the union"
    assert by_flag.get(False), "the prose link was wrongly marked report-only"


def test_classify_never_yields_an_anchorable_kind_for_a_report_only_link():
    """⚠️ The adversarial one (T017). The edit is produced when the classification says
    `web_anchor`; so the protection must live in the CLASSIFICATION, where the condition for
    writing is decided -- not in the loop that happens to call it today. Invoked directly,
    bypassing the normal call site."""
    link = WebLink(text="", href=LIVE, uuid=None, start=0, end=0, report_only=True)
    gu = GithubUrl(OWNER, REPO, "main", "docs/alive.md")
    fnd = _classify(link, gu, 200, UUID, True, Path("diagram.md"), {OWNER.casefold()})
    assert fnd.kind != "web_anchor", \
        "a report-only link was classified as anchorable: the edit loop is the only thing " \
        "standing between this and a corrupted diagram"


# --------------------------------------------------------------------------------------------
# T005-T010, T019 -- end to end
# --------------------------------------------------------------------------------------------

def _responses():
    return {LIVE: (200, f"---\nuuid: {UUID}\n---\n# alive\n")}   # DEAD is absent -> 404


def test_seeded_defect_is_caught_with_the_flag_on(tmp_path):
    """SC-019. The fixture is broken on purpose; a clean tree would prove nothing.

    A token is passed on purpose: without one a 404 is AMBIGUOUS (it could be a private repo the
    run cannot see), so darnlink honestly refuses to call the link broken. That is why the fleet's
    pre-push hook derives a token from `gh` before running this axis -- and why a test that omits
    it would be asserting the wrong thing."""
    root = _tree(tmp_path)
    findings, _ = check_web_links_online(root, "tok", _fetcher(_responses()), (),
                                         owners={OWNER.casefold()}, include_mermaid=True)
    hrefs = {f.href for f in findings if f.kind in ("web_not_found", "web_mismatch")}
    assert DEAD in hrefs
    assert LIVE not in hrefs


def test_the_same_defect_is_invisible_with_the_flag_off(tmp_path):
    """The other half of SC-019. If this ever agrees with the test above, the feature is not
    wired and the suite is green for the wrong reason."""
    root = _tree(tmp_path)
    findings, _ = check_web_links_online(root, None, _fetcher(_responses()), (),
                                         owners={OWNER.casefold()})
    assert DEAD not in {f.href for f in findings}


def test_disabled_is_byte_identical_in_output_and_exit_code(tmp_path, capsys):
    """SC-018 -- what makes this safe to ship into gates that have not opted in."""
    root = _tree(tmp_path)
    rc = main(["web-check", str(root), "--json"])
    first = capsys.readouterr().out
    rc2 = main(["web-check", str(root), "--json"])
    assert (rc, first) == (rc2, capsys.readouterr().out)
    assert DEAD not in first


def test_writing_mode_writes_nothing_when_the_only_candidates_are_in_a_diagram(tmp_path):
    """SC-023. A single byte of difference here is a corrupted drawing."""
    root = tmp_path / "repo"
    _w(root / "diagram.md", DIAGRAM)
    before = _checksums(root)
    _findings, edits = check_web_links_online(root, None, _fetcher(_responses()), (),
                                              owners={OWNER.casefold()}, include_mermaid=True)
    for path, text in edits.items():
        path.write_text(text, encoding="utf-8")
    assert _checksums(root) == before
    assert edits == {}


def test_a_prose_link_is_anchored_while_the_diagram_beside_it_is_untouched(tmp_path):
    """T016 -- the mixed file. This is the one that fails if report-only is applied per FILE
    instead of per LINK."""
    root = tmp_path / "repo"
    _w(root / "mixed.md", DIAGRAM + f"\nAnd a prose link: [alive]({LIVE})\n")
    _findings, edits = check_web_links_online(root, None, _fetcher(_responses()), (),
                                              owners={OWNER.casefold()}, include_mermaid=True)
    assert edits, "the prose link should still have been anchored"
    new = next(iter(edits.values()))
    fence_start = new.index("```mermaid")
    fence_end = new.index("```", fence_start + 3)
    assert "web-uuid" not in new[fence_start:fence_end], "an anchor was written inside the drawing"
    assert "web-uuid" in new[fence_end:]


def test_both_entry_points_agree_about_what_exists(tmp_path, capsys):
    """T007. A tool that reports a broken destination online and denies it offline is worse than
    no tool: it teaches you not to believe it."""
    root = _tree(tmp_path)
    main(["web-check", str(root), "--json", "--include-mermaid"])
    import json as _json
    offline = {ln["href"] for ln in _json.loads(capsys.readouterr().out)["links"]}
    findings, _ = check_web_links_online(root, "tok", _fetcher(_responses()), (),
                                         owners={OWNER.casefold()}, include_mermaid=True)
    assert offline == {f.href for f in findings}


def test_the_offline_report_says_which_links_can_never_be_anchored(tmp_path, capsys):
    """T018. The offline listing projects a link to {file, href, anchored} and drops the rest, so
    a consumer cannot tell 'never anchorable' from 'not anchored yet' -- the same defect, one
    layer out."""
    root = _tree(tmp_path)
    main(["web-check", str(root), "--json", "--include-mermaid"])
    import json as _json
    links = _json.loads(capsys.readouterr().out)["links"]
    diagram_links = [ln for ln in links if ln["href"] in (LIVE, DEAD)]
    assert diagram_links
    for ln in diagram_links:
        assert ln.get("report_only") is True


def test_a_repository_without_diagrams_is_unaffected(tmp_path, capsys):
    """FR-059."""
    root = tmp_path / "repo"
    _w(root / "plain.md", f"[alive]({LIVE})\n")
    main(["web-check", str(root), "--json"])
    off = capsys.readouterr().out
    main(["web-check", str(root), "--json", "--include-mermaid"])
    assert off == capsys.readouterr().out


def test_no_fetch_is_attempted_for_a_diagram_destination_when_disabled(tmp_path):
    """SC-022 -- the traffic half of 'a repository that never opted in is unaffected'."""
    root = _tree(tmp_path)
    asked = []

    def counting(gu: GithubUrl, token):
        asked.append(f"https://github.com/{gu.owner}/{gu.repo}/blob/{gu.ref}/{gu.path}")
        return _fetcher(_responses())(gu, token)

    check_web_links_online(root, None, counting, (), owners={OWNER.casefold()})
    assert DEAD not in asked and LIVE not in asked


# --------------------------------------------------------------------------------------------
# T019 -- the write operations are not amended by this feature (FR-053 / FR-015 stands)
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("robustify", [False, True])
def test_repair_and_robustify_never_touch_a_diagram(tmp_path, robustify):
    root = tmp_path / "repo"
    _w(root / "diagram.md", DIAGRAM)
    _w(root / "target.md", f"---\nuuid: {UUID}\n---\n# target\n")
    before = _checksums(root)
    argv = [str(root), "--write"] + (["--robustify"] if robustify else [])
    main(argv)
    assert _checksums(root) == before
