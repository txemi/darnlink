"""Feature 013 (EXPERIMENTAL spike): cross-repo web-link robustness, ONLINE-fetch design.

Network is never touched: every test injects a fake `fetcher` mapping a GithubUrl -> (status, text),
so the fetch layer is exercised deterministically. Demonstrates the chosen design on the real case
(ledger -> handbook by GitHub URL anchored to the destination's uuid): anchor a plain web link, verify
an anchored one, fail on mismatch/404, stay honest (web_unverifiable) on a private repo with no token,
and never fire in the core / offline mode.
"""
import hashlib
import json
from pathlib import Path

import pytest

from darnlink.cli import UNVERIFIABLE_PREVIEW, _run_web_check_cli, main
from darnlink.weblinks import (GithubUrl, check_web_links_online, find_web_links,
                               parse_github_url)

UUID = "3f9c1a2b-4d5e-6f70-8192-a3b4c5d6e7f8"
OTHER = "11111111-2222-3333-4444-555555555555"
URL = "https://github.com/example-org/handbook/blob/main/docs/living/service-topology.md"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _checksums(root: Path):
    return {p: hashlib.sha1(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*.md"))}


def _fetcher(responses):
    """Build a fake fetcher: maps a full blob URL -> (status, text). Never touches the network."""
    def f(gu: GithubUrl, token):
        key = f"https://github.com/{gu.owner}/{gu.repo}/blob/{gu.ref}/{gu.path}"
        return responses.get(key, (404, None))
    return f


# --- pure URL parser (FR-007) ---

def test_parse_github_blob_url():
    assert parse_github_url("https://github.com/example-org/handbook/blob/main/a/b/c.md") == \
        GithubUrl("example-org", "handbook", "main", "a/b/c.md")


def test_parse_raw_and_www():
    assert parse_github_url("https://www.github.com/o/r/raw/dev/x.md") == GithubUrl("o", "r", "dev", "x.md")


def test_parse_non_github_is_none():
    assert parse_github_url("https://example.com/foo") is None
    assert parse_github_url("https://gitlab.com/o/r/-/blob/main/x.md") is None


def test_contents_api_url():
    gu = GithubUrl("example-org", "handbook", "main", "docs/x.md")
    assert gu.contents_api_url() == \
        "https://api.github.com/repos/example-org/handbook/contents/docs/x.md?ref=main"


# --- link finder: robust vs plain web links, code fences ignored ---

def test_find_web_links_plain_and_anchored():
    content = (f"a [p]({URL})\n"
               f"b [q]({URL}) <!-- web-uuid: {UUID} -->\n"
               "c [local](x.md)\n")
    links = find_web_links(content)
    assert [l.uuid for l in links] == [None, UUID]


def test_find_web_links_skips_code_fence():
    content = f"```\n[x]({URL}) <!-- web-uuid: {UUID} -->\n```\n"
    from darnlink.links import code_spans
    assert find_web_links(content, code_spans(content)) == []


# --- ONLINE: anchor a plain web link (fetch dest, read uuid, propose/apply) ---

def test_online_anchor_plain_link_dry_run(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL})\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {UUID}\n---\n# dest\n")})
    findings, edits = check_web_links_online(tmp_path, None, fetch)
    assert [f.kind for f in findings] == ["web_anchor"]
    assert findings[0].anchored_uuid == UUID
    assert (tmp_path / "conta.md") in edits
    assert f"<!-- web-uuid: {UUID} -->" in edits[tmp_path / "conta.md"]
    # dry-run must not touch disk
    assert (tmp_path / "conta.md").read_text() == f"see [topo]({URL})\n"


def test_online_anchor_applied_with_write(tmp_path, capsys):
    _w(tmp_path / "conta.md", f"see [topo]({URL})\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {UUID}\n---\n")})
    code = _run_web_check_cli([str(tmp_path), "--online", "--write", "--json"], fetcher=fetch)
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["wrote"] == 1
    assert (tmp_path / "conta.md").read_text() == f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n"


def test_online_anchor_pending_exits_3(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL})\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {UUID}\n---\n")})
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch) == 3  # dry-run, anchor pending


# --- ONLINE: verify an already-anchored link ---

def test_online_verify_match_web_ok(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {UUID}\n---\n")})
    findings, edits = check_web_links_online(tmp_path, None, fetch)
    assert [f.kind for f in findings] == ["web_ok"]
    assert edits == {}


def test_online_verify_mismatch_exits_4(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {OTHER}\n---\n")})  # destination uuid differs
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch) == 4


def test_online_dest_has_no_uuid_is_mismatch(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (200, "# a destination with no frontmatter\n")})
    findings, _ = check_web_links_online(tmp_path, None, fetch)
    assert findings[0].kind == "web_mismatch"


# --- failure cases: 404, private-no-token, unparseable, network error ---

def test_online_404_WITH_token_is_web_not_found_exits_4(tmp_path, monkeypatch):
    """WITH a token, a 404 is a real break: the token distinguishes 'moved/deleted' from
    'private repo we cannot see', so a 404 can be trusted as broken -> fail-closed (exit 4)."""
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({})  # every URL -> 404
    findings, _ = check_web_links_online(tmp_path, token="tok", fetcher=fetch)
    assert findings[0].kind == "web_not_found"
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch) == 4


def test_online_404_WITHOUT_token_is_unverifiable_exits_0(tmp_path, monkeypatch):
    """WITHOUT a token, a 404 is AMBIGUOUS — GitHub 404s a private repo we can't see exactly like a
    genuinely moved file — so it must NOT fail the gate, or every tokenless clone false-reds on each
    private cross-repo link (the real 'false breaks' that blocked pushes). -> web_unverifiable, exit 0."""
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({})  # every URL -> 404
    findings, _ = check_web_links_online(tmp_path, token=None, fetcher=fetch)
    assert findings[0].kind == "web_unverifiable"
    assert "no token" in findings[0].detail
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch) == 0


def test_online_private_no_token_is_unverifiable(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (403, None)})  # private repo, no token -> 403
    findings, _ = check_web_links_online(tmp_path, token=None, fetcher=fetch)
    assert findings[0].kind == "web_unverifiable"
    assert "no token provided" in findings[0].detail
    # unverifiable does not fail the exit (not a broken link, just unconfirmed)
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch) == 0


def test_online_private_with_token_reads_uuid(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")

    def fetch(gu, token):  # 403 without token, 200 with it
        return (200, f"---\nuuid: {UUID}\n---\n") if token else (403, None)

    findings, _ = check_web_links_online(tmp_path, token="ghp_fake", fetcher=fetch)
    assert findings[0].kind == "web_ok"


def test_online_network_error_is_unverifiable(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (-1, None)})  # URLError/timeout mapped to -1
    findings, _ = check_web_links_online(tmp_path, None, fetch)
    assert findings[0].kind == "web_unverifiable"


def test_online_unparseable_url_is_unverifiable(tmp_path):
    _w(tmp_path / "conta.md", f"see [x](https://example.com/whatever) <!-- web-uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(tmp_path, None, _fetcher({}))
    assert findings[0].kind == "web_unverifiable"


def test_many_unverifiable_are_summarised_not_listed_one_by_one(tmp_path, capsys):
    """web_unverifiable never fails the exit, so listing every one of them on a docs repo full of
    ordinary external URLs drowns the actionable findings (and floods whoever reads the output).
    The total stays in the summary line and --json keeps them all, so nothing is silenced."""
    n = UNVERIFIABLE_PREVIEW + 5
    for i in range(n):
        _w(tmp_path / f"doc{i}.md", f"see [x](https://example.com/{i})\n")

    code = _run_web_check_cli([str(tmp_path), "--online"], fetcher=_fetcher({}))
    out = capsys.readouterr().out

    assert code == 0
    assert out.count("[web_unverifiable]") == UNVERIFIABLE_PREVIEW
    assert f"... and {n - UNVERIFIABLE_PREVIEW} more web_unverifiable" in out
    assert f"unverifiable {n}" in out  # the real total is never hidden


def test_json_still_carries_every_unverifiable(tmp_path, capsys):
    n = UNVERIFIABLE_PREVIEW + 5
    for i in range(n):
        _w(tmp_path / f"doc{i}.md", f"see [x](https://example.com/{i})\n")

    _run_web_check_cli([str(tmp_path), "--online", "--json"], fetcher=_fetcher({}))
    out = json.loads(capsys.readouterr().out)

    assert out["web_unverifiable"] == n
    assert len([f for f in out["findings"] if f["kind"] == "web_unverifiable"]) == n


# --- OFF by default: no --online => no network, no writes, exit 0 ---

def test_offline_default_makes_no_fetch_and_lists(tmp_path, capsys):
    _w(tmp_path / "conta.md", f"see [topo]({URL})\n")

    def explode(gu, token):  # must never be called without --online
        raise AssertionError("fetcher called without --online")

    code = _run_web_check_cli([str(tmp_path), "--json"], fetcher=explode)
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["online"] is False and out["web_links_seen"] == 1


def test_write_without_online_is_usage_error(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL})\n")
    assert _run_web_check_cli([str(tmp_path), "--write"]) == 1


# --- core is untouched: repair / robustify / check ignore web links entirely ---

def test_core_ignores_web_links(tmp_path):
    # Blocker 1: the web anchor is `<!-- web-uuid: X -->`, NOT the core's `<!-- uuid: X -->`. This is
    # what lets ANY repo's core gate — even one without darnlink-web's is_web_href guard — stay clean
    # next to a cross-repo web link: the core's marker regex simply never matches it, so it never tries
    # to resolve X locally (which would fail: X lives in another repo) and never fails the gate.
    from darnlink.links import find_robust_links
    src = f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n"
    assert find_robust_links(src) == []               # the core does not even SEE it as a robust link
    _w(tmp_path / "conta.md", src)                    # uuid not local
    assert main([str(tmp_path)]) == 0                 # repair: web link inert
    assert main([str(tmp_path), "--robustify"]) == 0  # robustify: not a local .md
    assert main(["check", str(tmp_path)]) == 0        # check: both axes clean


# --- report-only unless --write: verify path never mutates disk ---

def test_verify_never_writes(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {OTHER}\n---\n")})
    before = _checksums(tmp_path)
    _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch)  # mismatch, but read-only
    assert _checksums(tmp_path) == before


def test_bad_flag_exits_1(tmp_path):
    with pytest.raises(SystemExit) as e:
        _run_web_check_cli([str(tmp_path), "--nonexistent"])
    assert e.value.code == 1


def test_online_respects_excludes(tmp_path):
    # a web link inside an --exclude'd directory (a vendored clone of a foreign repo) must not be
    # fetched or anchored — otherwise web-check would inject uuids into someone else's checkout.
    URL = "https://github.com/o/r/blob/main/dest.md"
    (tmp_path / "clones" / "foreign").mkdir(parents=True)
    (tmp_path / "clones" / "foreign" / "A.md").write_text(f"See [x]({URL})\n", encoding="utf-8")
    fetch = _fetcher({URL: (200, "---\nuuid: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n---\n")})
    findings, edits = check_web_links_online(tmp_path, None, fetch, excludes={"clones"})
    assert findings == []
    assert edits == {}


# --- transient-retry in default_fetcher (v0.15.0): a flaky 404/5xx must not become web_not_found ---

def test_default_fetcher_retries_transient_404_then_succeeds(monkeypatch):
    """A transient 404 (rate-limit / CDN-cold-right-after-push) clears on retry -> final 200, no false
    web_not_found. `sleep` is injected as a no-op so the test never waits."""
    import darnlink.weblinks as wl
    gu = wl.GithubUrl("o", "r", "main", "a.md")
    seq = iter([(404, None), (200, "---\nuuid: x\n---\n")])
    monkeypatch.setattr(wl, "_fetch_once", lambda g, t: next(seq))
    status, text = wl.default_fetcher(gu, None, attempts=3, sleep=lambda _s: None)
    assert status == 200 and text is not None


def test_default_fetcher_persistent_404_stays_404(monkeypatch):
    """A genuinely dead link 404s on EVERY attempt -> still reported 404 (retry hides no real break)."""
    import darnlink.weblinks as wl
    gu = wl.GithubUrl("o", "r", "main", "gone.md")
    calls = {"n": 0}
    def _once(g, t):
        calls["n"] += 1
        return (404, None)
    monkeypatch.setattr(wl, "_fetch_once", _once)
    status, _ = wl.default_fetcher(gu, None, attempts=3, sleep=lambda _s: None)
    assert status == 404 and calls["n"] == 3  # exhausted all attempts


def test_default_fetcher_no_retry_on_200(monkeypatch):
    """A clean first response returns immediately — no wasted retries on the happy path."""
    import darnlink.weblinks as wl
    gu = wl.GithubUrl("o", "r", "main", "a.md")
    calls = {"n": 0}
    def _once(g, t):
        calls["n"] += 1
        return (200, "---\nuuid: x\n---\n")
    monkeypatch.setattr(wl, "_fetch_once", _once)
    status, _ = wl.default_fetcher(gu, None, attempts=3, sleep=lambda _s: None)
    assert status == 200 and calls["n"] == 1


# --- v0.17.0: 404 in a repo we cannot read -> unverifiable, not a break (cross-org private repos) ---

def test_classify_status_minus2_is_unverifiable():
    """The -2 sentinel (404 whose destination repo is not readable with the token) classifies as
    web_unverifiable — a private cross-org repo's 404 is ambiguous, not a break."""
    from darnlink.weblinks import _classify, WebLink
    from pathlib import Path
    gu = GithubUrl("acme-tech", "some-repo", "main", "a.md")
    link = WebLink(href="https://github.com/acme-tech/some-repo/blob/main/a.md", text="x",
                   start=0, end=0, uuid="1111")
    fnd = _classify(link, gu, -2, None, True, Path("f.md"))
    assert fnd.kind == "web_unverifiable"
    assert "not readable" in fnd.detail


def test_default_fetcher_404_inaccessible_repo_returns_minus2(monkeypatch):
    """WITH a token, a 404 whose repo is NOT accessible -> sentinel -2 (so _classify -> unverifiable).
    A 404 whose repo IS accessible stays 404 (a real break)."""
    import darnlink.weblinks as wl
    wl._repo_accessible.cache_clear()
    gu = wl.GithubUrl("otherorg", "priv", "main", "gone.md")
    monkeypatch.setattr(wl, "_fetch_once", lambda g, t: (404, None))
    monkeypatch.setattr(wl, "_repo_accessible", lambda o, r, t: False)  # repo not readable
    assert wl.default_fetcher(gu, "tok", attempts=1, sleep=lambda _s: None) == (-2, None)
    monkeypatch.setattr(wl, "_repo_accessible", lambda o, r, t: True)   # repo readable
    assert wl.default_fetcher(gu, "tok", attempts=1, sleep=lambda _s: None) == (404, None)


def test_default_fetcher_404_no_token_skips_repo_check(monkeypatch):
    """WITHOUT a token, the repo-accessibility refinement is not attempted -> plain 404 (unverifiable
    handling stays in _classify)."""
    import darnlink.weblinks as wl
    gu = wl.GithubUrl("o", "r", "main", "gone.md")
    monkeypatch.setattr(wl, "_fetch_once", lambda g, t: (404, None))
    called = {"n": 0}
    monkeypatch.setattr(wl, "_repo_accessible", lambda o, r, t: called.__setitem__("n", called["n"]+1) or False)
    assert wl.default_fetcher(gu, None, attempts=1, sleep=lambda _s: None) == (404, None)
    assert called["n"] == 0  # no token -> no repo check
