"""Feature 016: fail on cross-repo web links to YOUR OWN repos whose destination has no `uuid`.

One test per acceptance scenario of `specs/016-own-repo-web-strictness/spec.md`, in order, so a
failure names the requirement it breaks. The fetch layer is mocked everywhere — no test touches the
network. Scenarios 8 and 9 additionally build a real git fixture, because FR-002 resolves the owner
through `git config` and a hand-rolled `.git/config` would not exercise it.

Every assertion here was validated by mutation while it was written: break what it covers and it
fails. That is not ceremony — three tests in this feature's own history passed while proving nothing
(one claimed to reach a sentinel the guard intercepted first; another used filler from the very
bucket it claimed to distinguish).
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from darnlink.cli import _run_web_check_cli
from darnlink.weblinks import GithubUrl, check_web_links_online

UUID = "3f9c1a2b-4d5e-6f70-8192-a3b4c5d6e7f8"
OTHER = "11111111-2222-3333-4444-555555555555"
SHA40 = "30066b0042d0c5928d959e288144300cb28196c9"
SHA7 = "30066b0"

OWNED = "https://github.com/owned/repo/blob/main/a.md"
FOREIGN = "https://github.com/someone-else/repo/blob/main/a.md"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _fetcher(responses, calls=None):
    """Maps a full blob URL -> (status, text). Anything unlisted 404s. `calls` records every fetch."""
    def f(gu: GithubUrl, token):
        key = f"https://github.com/{gu.owner}/{gu.repo}/blob/{gu.ref}/{gu.path}"
        if calls is not None:
            calls.append(key)
        return responses.get(key, (404, None))
    return f


def _no_uuid(text="# a destination with no frontmatter\n"):
    return (200, text)


def _with_uuid(u=UUID):
    return (200, f"---\nuuid: {u}\n---\n# dest\n")


def _kinds(tmp_path, fetch, owners=frozenset({"owned"})):
    findings, edits = check_web_links_online(tmp_path, None, fetch, owners=owners)
    return [f.kind for f in findings], findings, edits


#: A git hook exports GIT_DIR and friends, and they override `-C`. Without stripping them these
#: fixtures build (and then read) the WRONG repository — which is exactly how this was found: the
#: suite passed standalone and failed under this project's own pre-commit hook.
_GIT_ENV = {k: v for k, v in os.environ.items()
            if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}


def _git_repo(tmp_path, origin: str | None):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=_GIT_ENV)
    if origin:
        subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", origin],
                       check=True, env=_GIT_ENV)
    return tmp_path


# 1
def test_owned_destination_without_uuid_fails_and_says_where(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    kinds, findings, _ = _kinds(tmp_path, _fetcher({OWNED: _no_uuid()}))
    assert kinds == ["web_own_no_uuid"]
    assert "owned/repo" in findings[0].detail and "a.md" in findings[0].detail
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned"],
                              fetcher=_fetcher({OWNED: _no_uuid()})) == 4


# 2
def test_a_destination_you_do_not_own_is_unchanged(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({FOREIGN})\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({FOREIGN: _no_uuid()}))
    assert kinds == ["web_unverifiable"]
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned"],
                              fetcher=_fetcher({FOREIGN: _no_uuid()})) == 0


# 3
def test_with_no_owner_set_nothing_changes(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({OWNED: _no_uuid()}), owners=frozenset())
    assert kinds == ["web_unverifiable"]
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=_fetcher({OWNED: _no_uuid()})) == 0


# 4
def test_an_owned_destination_that_has_a_uuid_still_anchors(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    kinds, _, edits = _kinds(tmp_path, _fetcher({OWNED: _with_uuid()}))
    assert kinds == ["web_anchor"] and edits
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--write"],
                              fetcher=_fetcher({OWNED: _with_uuid()})) == 0
    assert f"<!-- web-uuid: {UUID} -->" in (tmp_path / "src.md").read_text(encoding="utf-8")


# 5
@pytest.mark.parametrize("path,expected", [
    ("tool.py", "web_unverifiable"),   # cannot carry frontmatter at all (FR-005)
    ("A.MD", "web_own_no_uuid"),       # Markdown, case-folded like iter_markdown_files
])
def test_only_markdown_destinations_can_be_asked_for_a_uuid(tmp_path, path, expected):
    url = f"https://github.com/owned/repo/blob/main/{path}"
    _w(tmp_path / "src.md", f"see [x]({url})\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({url: _no_uuid()}))
    assert kinds == [expected]


# 6
@pytest.mark.parametrize("ref,expected", [
    (SHA40, "web_unverifiable"),
    (SHA7, "web_unverifiable"),
    (SHA40.upper(), "web_unverifiable"),   # GitHub accepts it in ?ref=, so the rule must fold case
    ("v1.2.3", "web_own_no_uuid"),         # a tag is indistinguishable from a branch WITHOUT the network
])
def test_a_commit_pinned_destination_can_never_be_fixed_so_it_never_fails(tmp_path, ref, expected):
    url = f"https://github.com/owned/repo/blob/{ref}/a.md"
    _w(tmp_path / "src.md", f"see [x]({url})\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({url: _no_uuid()}))
    assert kinds == [expected]


@pytest.mark.parametrize("ref", ["release-deadbeef", "v1.2-abc1234", "deadbeef-wip"])
def test_a_ref_that_merely_ends_in_hex_is_not_a_commit(tmp_path, ref):
    """FR-006 matches the WHOLE ref. Anchoring it loosely would excuse `release-deadbeef` — a branch,
    perfectly fixable — and the direction of that error is a false green."""
    url = f"https://github.com/owned/repo/blob/{ref}/a.md"
    _w(tmp_path / "src.md", f"see [x]({url})\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({url: _no_uuid()}))
    assert kinds == ["web_own_no_uuid"]


def test_a_ref_longer_than_a_sha_is_not_one(tmp_path):
    """`{7,40}` is a range with a ceiling for a reason: 41 hex characters is not a commit id, and
    treating it as immutable would suppress a finding that is perfectly fixable."""
    url = "https://github.com/owned/repo/blob/" + "a" * 41 + "/a.md"
    _w(tmp_path / "src.md", f"see [x]({url})\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({url: _no_uuid()}))
    assert kinds == ["web_own_no_uuid"]


def test_a_run_with_only_exempt_links_still_counts_them(tmp_path, capsys):
    """FR-016 asks for both kinds in the summary line. Keying the extra counters on the FAILING kind
    alone would drop them from a run that has only exemptions — the audit trail the marker promises."""
    _w(tmp_path / "src.md", f"see [x]({OWNED}) <!-- darnlink-own-exempt -->\n")
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned"],
                       fetcher=_fetcher({OWNED: _no_uuid()}))
    assert "own-exempt 1" in capsys.readouterr().out


def test_the_carve_out_is_not_a_verdict(tmp_path):
    """FR-005/FR-006 say when FR-004 must NOT fire; they do not turn a link into anything. Read as a
    terminal step they would silently change behaviour FR-007 freezes: this link is `web_anchor`."""
    url = f"https://github.com/owned/repo/blob/{SHA40}/a.md"
    _w(tmp_path / "src.md", f"see [x]({url})\n")
    kinds, _, edits = _kinds(tmp_path, _fetcher({url: _with_uuid()}))
    assert kinds == ["web_anchor"] and edits


def test_a_bom_in_the_destination_does_not_hide_its_uuid(tmp_path):
    """A Windows-authored destination arrives with a BOM. Read as plain utf-8 it sits in front of the
    `---`, the frontmatter reader sees none, and 016 then reports a file that HAS a uuid as lacking
    one — exit 4 over an instruction nobody can follow. `tests/test_bom.py` already declares this
    invariant for the LOCAL path; the web path was left out of it."""
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    bom = (200, "\ufeff" + f"---\nuuid: {UUID}\n---\n# dest\n")
    kinds, findings, edits = _kinds(tmp_path, _fetcher({OWNED: bom}))
    assert kinds == ["web_anchor"] and edits          # NOT web_own_no_uuid
    # the uuid too, not just the kind: a "fix" that invented one would pass on kind alone
    assert findings[0].anchored_uuid == UUID
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned"],
                              fetcher=_fetcher({OWNED: bom})) == 3


def test_the_wire_half_of_the_bom_fix_is_pinned_too(monkeypatch):
    """The `utf-8-sig` decode in `_fetch_once` is the belt to the `lstrip`'s braces, and it is
    unobservable through the CLI — the strip neutralises it downstream, so no end-to-end test can kill
    it. Pinned at the seam instead: bytes off the wire, text out."""
    import io
    from darnlink.weblinks import _fetch_once

    class _Resp(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: _Resp(b"\xef\xbb\xbf---\nuuid: x\n---\n"))
    status, text = _fetch_once(GithubUrl("o", "r", "main", "a.md"), None)
    assert status == 200 and text.startswith("---")   # not "\ufeff---"


def test_a_bom_does_not_invent_a_uuid_either(tmp_path):
    """The other direction, so the fix cannot be 'strip anything that looks like a BOM': a destination
    with a BOM and NO uuid is still the finding it always was."""
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    bom = (200, "\ufeff# a destination with no frontmatter\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({OWNED: bom}))
    assert kinds == ["web_own_no_uuid"]


# 7
def test_a_404_keeps_its_kind_whether_or_not_you_own_it(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED}) <!-- web-uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(tmp_path, None, _fetcher({}), owners=frozenset({"owned"}))
    assert findings[0].kind == "web_unverifiable"          # no token: ambiguous, as today
    findings, _ = check_web_links_online(tmp_path, "tok", _fetcher({}), owners=frozenset({"owned"}))
    assert findings[0].kind == "web_not_found"             # with token: a real break, as today


# 8
@pytest.mark.parametrize("origin", ["git@github.com:owned/src.git",
                                    "https://github.com/owned/src.git"])
def test_own_from_origin_reads_the_remote(tmp_path, origin):
    _git_repo(tmp_path, origin)
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own-from-origin"],
                              fetcher=_fetcher({OWNED: _no_uuid()})) == 4


def test_own_from_origin_unions_with_explicit_owners(tmp_path, capsys):
    _git_repo(tmp_path, "git@github.com:owned/src.git")
    _w(tmp_path / "src.md", f"a [x]({OWNED})\nb [y]({FOREIGN})\n")
    code = _run_web_check_cli([str(tmp_path), "--online", "--own", "someone-else",
                               "--own-from-origin", "--json"],
                              fetcher=_fetcher({OWNED: _no_uuid(), FOREIGN: _no_uuid()}))
    # `code == 4` alone proves nothing: the origin owner produces it on its own. BOTH owners must be
    # in the set, so both destinations must fail.
    assert json.loads(capsys.readouterr().out)["web_own_no_uuid"] == 2
    assert code == 4


# 9
def test_own_from_origin_that_cannot_resolve_is_a_usage_error(tmp_path, capsys):
    _git_repo(tmp_path, None)  # a repo with no origin
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    calls = []
    assert _run_web_check_cli([str(tmp_path), "--online", "--own-from-origin"],
                              fetcher=_fetcher({}, calls)) == 1
    assert calls == []  # no findings emitted, nothing fetched
    assert "could not resolve" in capsys.readouterr().err


def test_it_is_still_a_usage_error_when_explicit_owners_were_given(tmp_path):
    """The owner set would NOT be empty. The rule is about the request, not the resulting set:
    answering a narrower question than the one asked is the same false pass by a smaller door."""
    _git_repo(tmp_path, None)
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-from-origin"],
                              fetcher=_fetcher({})) == 1


# 10
def test_ownership_costs_no_extra_fetch(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    without, with_ = [], []
    check_web_links_online(tmp_path, None, _fetcher({OWNED: _no_uuid()}, without), owners=frozenset())
    check_web_links_online(tmp_path, None, _fetcher({OWNED: _no_uuid()}, with_),
                           owners=frozenset({"owned"}))
    assert with_ == without == [OWNED]


# 11
def test_the_exemption_marker_takes_a_link_out_of_three_verdicts(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED}) <!-- darnlink-own-exempt -->\n")
    kinds, findings, _ = _kinds(tmp_path, _fetcher({OWNED: _no_uuid()}))
    assert kinds == ["web_own_exempt"]
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned"],
                              fetcher=_fetcher({OWNED: _no_uuid()})) == 0
    # …and without the marker the very same link fails
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned"],
                              fetcher=_fetcher({OWNED: _no_uuid()})) == 4


def test_an_exempt_link_is_never_anchored(tmp_path):
    before = f"see [x]({OWNED}) <!-- darnlink-own-exempt -->\n"
    _w(tmp_path / "src.md", before)
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--write"],
                              fetcher=_fetcher({OWNED: _with_uuid()})) == 0
    assert (tmp_path / "src.md").read_text(encoding="utf-8") == before


def test_an_exempt_anchored_link_whose_destination_drifted_is_not_a_mismatch(tmp_path):
    """The third exemption, and the one that makes the hatch escape: a destination that regenerates is
    precisely one whose uuid drifts, so without it the normal migration path leaves a permanent exit 4."""
    _w(tmp_path / "src.md",
       f"see [x]({OWNED}) <!-- web-uuid: {UUID} --> <!-- darnlink-own-exempt -->\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({OWNED: _with_uuid(OTHER)}))
    assert kinds == ["web_own_exempt"]


def test_both_markers_in_the_normative_order_round_trip(tmp_path):
    before = f"see [x]({OWNED}) <!-- web-uuid: {UUID} --> <!-- darnlink-own-exempt -->\n"
    _w(tmp_path / "src.md", before)
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--write"],
                       fetcher=_fetcher({OWNED: _with_uuid()}))
    assert (tmp_path / "src.md").read_text(encoding="utf-8") == before


def test_the_corruption_case_does_not_append_a_second_anchor(tmp_path):
    """With the anchor written AFTER the exemption the tail regex cannot see it, so the link reads as
    plain. The exemption must still be honoured, or `--write` leaves two anchors on one line."""
    before = f"see [x]({OWNED}) <!-- darnlink-own-exempt --> <!-- web-uuid: {UUID} -->\n"
    _w(tmp_path / "src.md", before)
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--write"],
                       fetcher=_fetcher({OWNED: _with_uuid()}))
    after = (tmp_path / "src.md").read_text(encoding="utf-8")
    assert after.count("web-uuid:") == 1 and after == before


def test_the_marker_does_not_reach_across_a_blank_line(tmp_path):
    """FR-011 says the marker is recognised immediately after the `)` or the anchor, and NOWHERE else.
    Written on its own line — the natural way to write it for the link BELOW — a lax `\\s*` made it
    exempt the link ABOVE, suppressing a real web_mismatch and turning exit 4 into a green run."""
    _w(tmp_path / "src.md",
       f"see [x]({OWNED}) <!-- web-uuid: {UUID} -->\n\n<!-- darnlink-own-exempt -->\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({OWNED: _with_uuid(OTHER)}))
    assert kinds == ["web_mismatch"]


# 12
@pytest.mark.parametrize("url", [
    "https://github.com/owned/repo/blob/main/tool.py",
    f"https://github.com/owned/repo/blob/{SHA40}/a.md",
])
def test_the_exemption_wins_over_the_other_exclusions(tmp_path, url):
    _w(tmp_path / "src.md", f"see [x]({url}) <!-- darnlink-own-exempt -->\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({url: _no_uuid()}))
    assert kinds == ["web_own_exempt"]


def test_an_exempt_link_that_verifies_cleanly_is_still_reported_as_exempt(tmp_path):
    _w(tmp_path / "src.md",
       f"see [x]({OWNED}) <!-- web-uuid: {UUID} --> <!-- darnlink-own-exempt -->\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({OWNED: _with_uuid()}))
    assert kinds == ["web_own_exempt"]   # NOT web_ok: the marker describes the link, not the run


def test_status_decides_before_the_exemption(tmp_path):
    """A dead link is dead whether or not its destination regenerates."""
    _w(tmp_path / "src.md", f"see [x]({OWNED}) <!-- darnlink-own-exempt -->\n")
    findings, _ = check_web_links_online(tmp_path, "tok", _fetcher({}), owners=frozenset({"owned"}))
    assert findings[0].kind == "web_not_found"


@pytest.mark.parametrize("leaked", [
    ("GIT_DIR", "GIT_WORK_TREE"),
    ("GIT_COMMON_DIR",),            # redirects on its own; dropping it from the strip list is silent
])
def test_origin_is_read_from_the_scanned_repo_even_under_a_git_hook(tmp_path, monkeypatch, leaked):
    """A git hook exports GIT_DIR/GIT_WORK_TREE, and inherited they OVERRIDE `-C`. The gate runs
    darnlink FROM a hook, so this is the normal case: without stripping them the answer is about the
    hook's repository, silently and with a plausible owner."""
    scanned = _git_repo(tmp_path / "scanned", "git@github.com:owned/src.git")
    other = _git_repo(tmp_path / "other", "git@github.com:hijacked/x.git")
    _w(scanned / "src.md", f"see [x]({OWNED})\n")
    for var in leaked:
        monkeypatch.setenv(var, str(other / ".git") if var != "GIT_WORK_TREE" else str(other))
    # owner comes from `scanned` (owned/...), not from `other` (hijacked/...), so the link fails
    assert _run_web_check_cli([str(scanned), "--online", "--own-from-origin"],
                              fetcher=_fetcher({OWNED: _no_uuid()})) == 4


# 13
@pytest.mark.parametrize("flag,url", [("OWNED", OWNED),
                                      ("owned", "https://github.com/OWNED/repo/blob/main/a.md")])
def test_owner_matching_folds_case(tmp_path, flag, url):
    _w(tmp_path / "src.md", f"see [x]({url})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", flag],
                              fetcher=_fetcher({url: _no_uuid()})) == 4


@pytest.mark.parametrize("origin,owned", [
    ("https://notgithub.com/evil/src.git", False),   # only ENDS in github.com — must not resolve
    ("https://github.com.evil.test/evil/src.git", False),
    ("ssh://git@github.com/owned/src.git", True),
    ("https://GitHub.com/owned/src.git", True),      # hostnames are case-insensitive
    ("https://user@github.com/owned/src.git", True),
])
def test_only_a_real_github_origin_resolves(tmp_path, origin, owned):
    _git_repo(tmp_path, origin)
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    code = _run_web_check_cli([str(tmp_path), "--online", "--own-from-origin"],
                              fetcher=_fetcher({OWNED: _no_uuid()}))
    assert code == (4 if owned else 1)


def test_an_empty_owner_is_a_usage_error(tmp_path):
    """`--own ""` owns nothing, yet it would satisfy the --own-max guard — the very thing that guard
    exists to prevent."""
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", ""], fetcher=_fetcher({})) == 1


# 14
def test_the_budget_silences_the_verdict_never_the_finding(tmp_path, capsys):
    b = "https://github.com/owned/repo/blob/main/b.md"
    _w(tmp_path / "src.md", f"a [x]({OWNED})\nb [y]({b})\n")
    resp = {OWNED: _no_uuid(), b: _no_uuid()}
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "2"],
                              fetcher=_fetcher(resp)) == 0
    out = capsys.readouterr().out
    assert out.count("[web_own_no_uuid]") == 2 and "clean" not in out
    # AT the budget is where the ratchet matters most — you are at the ceiling. Without an assert here
    # the requirement passed while the nudge was silent (the code said `< own_max`); the wording it
    # then grew was a no-op instruction, so what is pinned is the third branch, not the second.
    assert "exactly at the budget" in out
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "1"],
                              fetcher=_fetcher(resp)) == 4


def test_the_budget_nudges_you_to_lower_it(tmp_path, capsys):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "3"],
                       fetcher=_fetcher({OWNED: _no_uuid()}))
    out = capsys.readouterr().out
    assert "lower --own-max to 1" in out
    assert "under budget)" in out      # not "at the budget": 1 finding, budget of 3


def test_a_budgeted_finding_does_not_shield_a_real_break(tmp_path, monkeypatch):
    """The token matters: without one a 404 is ambiguous by design (013's contract), so there would be
    no real break to shield and the test would pass for the wrong reason."""
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    dead = "https://github.com/owned/repo/blob/main/dead.md"
    _w(tmp_path / "src.md", f"a [x]({OWNED})\nb [y]({dead}) <!-- web-uuid: {UUID} -->\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "5"],
                              fetcher=_fetcher({OWNED: _no_uuid()})) == 4


def test_the_ratchet_is_not_hidden_by_another_failure(tmp_path, monkeypatch, capsys):
    """FR-013 conditions the OUTCOME WORD on the exit code, not the nudges — and the runs most likely
    to be read are the failing ones."""
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    dead = "https://github.com/owned/repo/blob/main/dead.md"
    _w(tmp_path / "src.md",
       f"a [x]({OWNED})\nb [y]({dead}) <!-- web-uuid: {UUID} -->\n")
    code = _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "5"],
                              fetcher=_fetcher({OWNED: _no_uuid()}))
    out = capsys.readouterr().out
    assert code == 4 and "integrity failure" in out
    assert "lower --own-max to 1" in out          # the ratchet still speaks
    assert "under budget" not in out              # …but it does not relabel the failure


def test_a_homograph_host_is_not_github(tmp_path):
    """IGNORECASE without ASCII folds U+0131 to `i`, so `gıthub.com/evil` resolved to owner `evil`."""
    _git_repo(tmp_path, "https://g\u0131thub.com/evil/src.git")
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own-from-origin"],
                              fetcher=_fetcher({})) == 1


@pytest.mark.parametrize("origin", ["ssh://git@github.com:22/owned/src.git",
                                    "ssh://git@ssh.github.com:443/owned/src.git"])
def test_githubs_own_firewall_forms_resolve(tmp_path, origin):
    """GitHub documents both for networks that block port 22. Rejecting them printed "a non-GitHub
    remote", which was simply false."""
    _git_repo(tmp_path, origin)
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own-from-origin"],
                              fetcher=_fetcher({OWNED: _no_uuid()})) == 4


def test_a_budget_without_an_owner_set_is_a_usage_error(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own-max", "1"],
                              fetcher=_fetcher({})) == 1


def test_two_links_to_one_destination_cost_two(tmp_path, capsys):
    """FR-012 counts findings, not destinations: one edit at the destination clears both, and adding a
    second link to a known-bad destination does move the number."""
    _w(tmp_path / "one.md", f"see [x]({OWNED})\n")
    _w(tmp_path / "two.md", f"see [y]({OWNED})\n")
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "9"],
                       fetcher=_fetcher({OWNED: _no_uuid()}))
    assert "lower --own-max to 2" in capsys.readouterr().out


def test_the_ceiling_message_does_not_ask_for_a_no_op(tmp_path, capsys):
    """At the ceiling — where every adoption sits — "lower it to N" when the budget IS N instructs
    nobody. Third branch, as `dangling_max` has."""
    b = "https://github.com/owned/repo/blob/main/b.md"
    _w(tmp_path / "src.md", f"a [x]({OWNED})\nb [y]({b})\n")
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "2"],
                       fetcher=_fetcher({OWNED: _no_uuid(), b: _no_uuid()}))
    out = capsys.readouterr().out
    assert "exactly at the budget" in out and "at the budget)" in out
    # The arithmetic is the point, and nothing pinned it: with `n - 1` mutated to `n` the message
    # became the very no-op this test is named after, and it still passed.
    assert "Fix one and lower it to 1." in out
    assert "lower --own-max to 2" not in out


def test_the_ceiling_arithmetic_at_one_points_at_zero(tmp_path, capsys):
    """N=1 is the edge of the ceiling branch: the next step is 0, i.e. drop the flag."""
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "1"],
                       fetcher=_fetcher({OWNED: _no_uuid()}))
    assert "Fix one and lower it to 0." in capsys.readouterr().out


def test_over_budget_says_by_how_much(tmp_path, capsys):
    """The run fails on its own, but a budget that goes silent exactly when it is exceeded is the one
    moment its number is worth reading (FR-013's fourth branch)."""
    b = "https://github.com/owned/repo/blob/main/b.md"
    _w(tmp_path / "src.md", f"a [x]({OWNED})\nb [y]({b})\n")
    code = _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "1"],
                              fetcher=_fetcher({OWNED: _no_uuid(), b: _no_uuid()}))
    out = capsys.readouterr().out
    assert code == 4 and "OVER the budget of 1" in out and "1 more than allowed" in out


def test_over_budget_says_by_how_much_not_just_that_it_is_over(tmp_path, capsys):
    """With n=2 and a budget of 1, `n - budget`, `budget` and `1` are the same number, so three
    different formulas passed the case above. This one separates them."""
    urls = [f"https://github.com/owned/repo/blob/main/f{i}.md" for i in range(5)]
    _w(tmp_path / "src.md", "".join(f"[x]({u})\n" for u in urls))
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "2"],
                       fetcher=_fetcher({u: _no_uuid() for u in urls}))
    assert "3 more than allowed" in capsys.readouterr().out


def test_a_clean_repo_is_told_the_budget_is_doing_nothing(tmp_path, capsys):
    """The zero branch is the only path to those tails, and no test ran it: three mutations of the
    wording survived. It is also the observable difference FR-012 requires between `--own-max 0` and
    omitting the flag."""
    _w(tmp_path / "src.md", f"see [x]({OWNED}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({OWNED: _with_uuid()})
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "0"], fetcher=fetch)
    assert "it is doing nothing" in capsys.readouterr().out
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "5"], fetcher=fetch)
    assert "so the rule is a rule again" in capsys.readouterr().out


def test_the_budget_is_distinguishable_in_json_too(tmp_path, capsys):
    """FR-012 requires it on BOTH surfaces: without `own_max` in the payload the two runs were
    byte-identical, so the machine surface — the one a gate reads — could not tell them apart."""
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    fetch = _fetcher({OWNED: _no_uuid()})
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "0", "--json"],
                       fetcher=fetch)
    zero = json.loads(capsys.readouterr().out)
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--json"], fetcher=fetch)
    omitted = json.loads(capsys.readouterr().out)
    assert zero["own_max"] == 0 and omitted["own_max"] is None
    assert zero["exit_code"] == omitted["exit_code"] == 4   # same verdict, distinguishable payload


def test_a_negative_budget_is_a_usage_error(tmp_path):
    """`--own-max -1` produced "OVER the budget of -1 … 2 more than allowed" for one finding."""
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "-1"],
                              fetcher=_fetcher({})) == 1


def test_the_two_exit_zero_qualifiers_compose(tmp_path, capsys):
    """A budgeted finding and an unreadable destination are different facts about the same exit 0.
    Keeping only one qualifier would silently revert the other's fix — both exist so that `clean` is
    never printed over something unexamined."""
    other = "https://example.com/whatever"
    _w(tmp_path / "src.md", f"a [x]({OWNED})\nb [y]({other})\n")
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "1"],
                       fetcher=_fetcher({OWNED: _no_uuid()}))
    out = capsys.readouterr().out
    assert "1 owned finding(s), at the budget" in out and "NOT verified" in out
    # order matters: the budget qualifier first, then what could not be read
    assert out.index("at the budget") < out.index("NOT verified")


def test_a_padded_owner_still_owns(tmp_path):
    """`--own " owned "` used to pass the emptiness check and match nothing: green run, and a message
    saying the budget was stale. A stray space producing a false green is the failure this feature
    exists to remove."""
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", " owned ", "--own-max", "0"],
                              fetcher=_fetcher({OWNED: _no_uuid()})) == 4


# 15
@pytest.mark.parametrize("marker", ["<!-- darnlink-ignore-file -->", "<!-- darnlink-ignore-links -->"])
def test_a_file_level_opt_out_filters_only_the_new_kind(tmp_path, marker):
    dead = "https://github.com/owned/repo/blob/main/dead.md"
    _w(tmp_path / "src.md",
       f"{marker}\n\na [x]({OWNED})\nb [y]({dead}) <!-- web-uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(tmp_path, "tok", _fetcher({OWNED: _no_uuid()}),
                                         owners=frozenset({"owned"}))
    kinds = sorted(f.kind for f in findings)
    # the new finding degrades to unverifiable — reported, not silent — and the real break survives
    assert kinds == ["web_not_found", "web_unverifiable"]


def test_an_ignore_block_region_still_emits_nothing_at_all(tmp_path):
    _w(tmp_path / "src.md",
       f"<!-- gen-start -->\nsee [x]({OWNED})\n<!-- gen-end -->\n")
    findings, _ = check_web_links_online(tmp_path, "tok", _fetcher({}), block_markers=("gen",),
                                         owners=frozenset({"owned"}))
    assert findings == []


# 16
def test_both_new_kinds_reach_json_and_the_text_report(tmp_path, capsys):
    _w(tmp_path / "src.md",
       f"a [x]({OWNED})\nb [y](https://github.com/owned/repo/blob/main/b.md) <!-- darnlink-own-exempt -->\n")
    resp = {OWNED: _no_uuid(), "https://github.com/owned/repo/blob/main/b.md": _no_uuid()}
    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--json"], fetcher=_fetcher(resp))
    out = json.loads(capsys.readouterr().out)
    assert out["web_own_no_uuid"] == 1 and out["web_own_exempt"] == 1
    assert {f["kind"] for f in out["findings"]} == {"web_own_no_uuid", "web_own_exempt"}

    _run_web_check_cli([str(tmp_path), "--online", "--own", "owned"], fetcher=_fetcher(resp))
    text = capsys.readouterr().out
    assert "own-no-uuid 1" in text and "own-exempt 1" in text
    assert "[web_own_no_uuid]" in text and "[web_own_exempt]" in text


def test_without_an_owner_set_the_summary_line_is_unchanged(tmp_path, capsys):
    """FR-001: byte-identical when the feature is not switched on."""
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    _run_web_check_cli([str(tmp_path), "--online"], fetcher=_fetcher({OWNED: _no_uuid()}))
    assert "own-no-uuid" not in capsys.readouterr().out


# 17
def test_the_message_says_what_to_do_and_does_not_promise_write(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    _, findings, _ = _kinds(tmp_path, _fetcher({OWNED: _no_uuid()}))
    d = findings[0].detail
    assert "owned" in d and "repo" in d and "a.md" in d and "frontmatter" in d
    assert "--write" not in d   # darnlink cannot fix this one; saying so would be a lie


# 18
@pytest.mark.parametrize("resp,kind", [
    ((403, None), "web_unverifiable"),
    ((-1, None), "web_unverifiable"),
    ((-2, None), "web_unverifiable"),
    ((-3, None), "web_unverifiable"),
])
def test_every_other_classification_is_untouched(tmp_path, resp, kind):
    _w(tmp_path / "src.md", f"see [x]({OWNED}) <!-- web-uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(tmp_path, "tok", _fetcher({OWNED: resp}),
                                         owners=frozenset({"owned"}))
    assert findings[0].kind == kind


def test_a_non_github_url_is_untouched_too(tmp_path):
    _w(tmp_path / "src.md", "see [x](https://example.com/whatever)\n")
    kinds, _, _ = _kinds(tmp_path, _fetcher({}))
    assert kinds == ["web_unverifiable"]


# 19
@pytest.mark.parametrize("flags", [["--own", "owned"], ["--own-from-origin"], ["--own-max", "1"]])
def test_the_new_flags_without_online_are_a_usage_error(tmp_path, flags):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    calls = []
    assert _run_web_check_cli([str(tmp_path)] + flags, fetcher=_fetcher({}, calls)) == 1
    assert calls == []


# 20
def test_at_zero_the_run_is_clean_and_says_to_drop_the_flag(tmp_path, capsys):
    """An obsolete --own-max on an already-clean repo must not make a clean run look qualified."""
    _w(tmp_path / "src.md", f"see [x]({OWNED}) <!-- web-uuid: {UUID} -->\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-max", "5"],
                              fetcher=_fetcher({OWNED: _with_uuid()})) == 0
    out = capsys.readouterr().out
    assert "(clean)" in out and "drop --own-max" in out


# 21
def test_unreadable_frontmatter_is_a_different_defect(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    broken = (200, "---\nuuid: [not, a, string]\n---\n# dest\n")
    kinds, findings, _ = _kinds(tmp_path, _fetcher({OWNED: broken}))
    assert kinds == ["web_unverifiable"]
    assert "not readable" in findings[0].detail and "add" not in findings[0].detail.lower()


def test_unreadable_frontmatter_keeps_todays_wording_when_the_feature_is_off(tmp_path):
    """FR-001 is about bytes, not only verdicts: with no owner set even the detail text must be what
    it is today, or a consumer that greps the report sees a change it never opted into."""
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    broken = (200, "---\nuuid: [not, a, string]\n---\n# dest\n")
    _, findings, _ = _kinds(tmp_path, _fetcher({OWNED: broken}), owners=frozenset())
    assert findings[0].detail == "destination has no uuid to anchor to"


# 22
def test_the_marker_is_honoured_with_no_owner_set_at_all(tmp_path):
    """The single deliberate exception to FR-001, and the default case during any rollout: nothing
    passes --own yet, and a marker that stopped working without it would let --write rewrite exactly
    the files it was placed to protect."""
    before = f"see [x]({OWNED}) <!-- darnlink-own-exempt -->\n"
    _w(tmp_path / "src.md", before)
    kinds, _, _ = _kinds(tmp_path, _fetcher({OWNED: _with_uuid()}), owners=frozenset())
    assert kinds == ["web_own_exempt"]
    assert _run_web_check_cli([str(tmp_path), "--online", "--write"],
                              fetcher=_fetcher({OWNED: _with_uuid()})) == 0
    assert (tmp_path / "src.md").read_text(encoding="utf-8") == before
