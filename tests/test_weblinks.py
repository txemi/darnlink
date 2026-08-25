"""Feature 013 (EXPERIMENTAL spike): cross-repo web-link robustness, ONLINE-fetch design.

Network is never touched: every test injects a fake `fetcher` mapping a GithubUrl -> (status, text),
so the fetch layer is exercised deterministically. Demonstrates the chosen design on the real case
(ledger -> handbook by GitHub URL anchored to the destination's uuid): anchor a plain web link, verify
an anchored one, fail on mismatch/404, stay honest (web_unverifiable) on a private repo with no token,
and never fire in the core / offline mode.
"""
import hashlib
import http.client
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


# --- failure cases: 404, 403-without-token, unparseable, network error ---

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


def test_online_403_without_a_token_is_reported_as_quota_not_as_a_private_repo(tmp_path):
    """A tokenless 403 is the ANONYMOUS RATE LIMIT, not a private repo.

    This test used to be called `..._private_no_token_...` and its fixture comment said
    "private repo, no token -> 403". That is backwards, and `_classify` says so itself:
    GitHub answers **404**, not 403, for a private repo we cannot see. So a 403 without a
    token is essentially always the 60/h-per-IP anonymous quota — which is what a caller
    behind a shared NAT hits. Naming it "private repo" sent readers hunting for a
    permissions problem they did not have, on destinations that were public and returned
    200 to a browser.
    """
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (403, None)})  # anonymous call, quota exhausted -> 403
    findings, _ = check_web_links_online(tmp_path, token=None, fetcher=fetch)
    assert findings[0].kind == "web_unverifiable"
    assert "quota" in findings[0].detail
    assert "private repo" not in findings[0].detail
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


# --- an href we cannot send: rejected, never fetched, never a crash ---

#: The real shape, from a scraped report mirrored into a docs repo: the "href" is two truncated URLs
#: with a space between them. It reached urllib and raised http.client.InvalidURL.
_SPACED_HREF = ("https://github.com/cli/cli/blob/30066b0042d0c5928d959e288144300cb28196c9/"
                "internal/codespaces/rpc/inv... https://github.com/cli/cli/blob/"
                "30066b0042d0c5928d959e288144300cb28196c9/internal/codespaces/rpc/invoker.go")


def test_parse_rejects_an_href_the_client_would_refuse():
    """The second assert is the one that matters: forbidding these characters only INSIDE the regex
    groups would parse this into a TRUNCATED path (`…/rpc/inv...`), whose 404 is then reported as a
    real break. A false `web_not_found` is worse than an honest `web_unverifiable`.

    The set is http.client's own, not the narrower whitespace class: scraped and OCR'd content carries
    0x7f and C0 characters, and any of them slipping past here reaches the fetch layer and produces a
    different verdict for the same defect."""
    assert parse_github_url(_SPACED_HREF) is None
    assert parse_github_url("https://github.com/o/r/blob/main/a b.md") is None
    for ch in ("\x7f", "\x01", "\x0e", "\t"):
        assert parse_github_url(f"https://github.com/o/r/blob/main/a{ch}b.md") is None


def test_online_unsendable_href_is_unverifiable_and_never_fetched(tmp_path):
    _w(tmp_path / "mirror" / "report.md", f"GitHub CLI [retrieves details]( {_SPACED_HREF})\n")

    def exploding_fetcher(gu, token):
        raise AssertionError(f"fetched an href we cannot send: {gu!r}")

    findings, edits = check_web_links_online(tmp_path, None, exploding_fetcher)
    assert [f.kind for f in findings] == ["web_unverifiable"]
    assert edits == {}


def test_contents_api_url_encodes_all_four_fields():
    """Not just the path: an owner or repo can carry non-ASCII as easily. http.client encodes the
    request line as ASCII and raises UnicodeEncodeError -- a ValueError, which escapes even an
    HTTPException belt -- so an ordinary accented filename killed the run."""
    url = GithubUrl("\xf3wner", "r\xe9po", "m\xe1in", "d\xf3cs/x.md").contents_api_url()
    url.encode("ascii")  # would raise before
    assert "%C3%B3wner" in url and "r%C3%A9po" in url


def test_already_encoded_path_is_not_double_encoded():
    """safe='/%' — a link written with %20 must not become %2520."""
    assert "a%20b.md" in GithubUrl("o", "r", "main", "a%20b.md").contents_api_url()


@pytest.mark.parametrize("exc", [
    http.client.InvalidURL("bad"),
    UnicodeEncodeError("ascii", "x", 0, 1, "ordinal not in range"),
])
def test_fetch_once_never_propagates_a_client_side_url_error(monkeypatch, exc):
    """Both escape `except (URLError, TimeoutError, OSError)` by a different route -- InvalidURL from
    HTTPException, UnicodeEncodeError from ValueError -- and both used to propagate and kill the run.
    Injected rather than provoked: with the URL encoded, provoking it would make the request VALID and
    this test would hit the network, which no test here may do."""
    from darnlink.weblinks import _fetch_once
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(exc))
    assert _fetch_once(GithubUrl("o", "r", "main", "a.md"), None) == (-3, None)


def test_a_client_side_url_error_is_not_retried(monkeypatch):
    """Deterministic: retrying spends real sleeps and can never succeed. -3 must stay OUT of
    _TRANSIENT_STATUSES -- that separation is the sentinel's whole purpose."""
    from darnlink.weblinks import _TRANSIENT_STATUSES, default_fetcher
    assert -3 not in _TRANSIENT_STATUSES
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(http.client.InvalidURL("bad")))
    slept = []
    assert default_fetcher(GithubUrl("o", "r", "main", "a.md"), None,
                           attempts=3, sleep=slept.append) == (-3, None)
    assert slept == []


def test_fetch_once_maps_a_transport_http_exception_to_the_network_sentinel(monkeypatch):
    """The other half of the widened except: a genuine transport HTTPException must still be -1, the
    RETRYABLE sentinel. If the two ever collapse, a flaky connection stops being retried or a
    malformed URL starts being."""
    from darnlink.weblinks import _TRANSIENT_STATUSES, _fetch_once
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(http.client.BadStatusLine("")))
    assert _fetch_once(GithubUrl("o", "r", "main", "a.md"), None) == (-1, None)
    assert -1 in _TRANSIENT_STATUSES


def test_repo_accessible_encodes_and_never_raises(monkeypatch):
    """Its twin was the one that crashed, so this one was left unencoded and its own docstring's
    'never raises' was false. Its real body runs in no other test in the suite."""
    from darnlink.weblinks import _repo_accessible
    seen = {}

    def capture(req, timeout=None):
        seen["url"] = req.full_url
        raise http.client.BadStatusLine("")

    _repo_accessible.cache_clear()
    monkeypatch.setattr("urllib.request.urlopen", capture)
    assert _repo_accessible("\xf3wner", "r\xe9po", None) is True
    _repo_accessible.cache_clear()
    seen["url"].encode("ascii")  # would raise before
    assert "%C3%B3wner" in seen["url"]


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


# --- the verdict line: it must not advise a remedy that cannot be taken ---

def test_verdict_line_is_plain_clean_when_nothing_was_unverifiable(tmp_path, capsys):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {UUID}\n---\n")})
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch) == 0
    assert "-> exit 0 (clean)" in capsys.readouterr().out


def test_verdict_line_does_not_offer_a_token_that_would_not_help(tmp_path, capsys):
    """`web_unverifiable` has seven causes and a token fixes two. Do not advise it over the other five.

    This is the defect the axis warning itself was added to prevent, one floor down: an alert that
    fires when it cannot help is learned and ignored. Measured on darnlink's own tree, where all 14
    unverifiable are non-GitHub URLs: the figure is IDENTICAL with and without a token, and the line
    still told the operator to export one they had already exported.
    """
    # A non-GitHub URL: unverifiable forever, with or without credentials.
    _w(tmp_path / "conta.md", "see [ext](https://example.com/a/b.md)\n")
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=_fetcher({})) == 0
    out = capsys.readouterr().out
    assert "unverifiable, NOT verified" in out          # it still says it did not look
    assert "GITHUB_TOKEN" not in out                    # but offers no remedy that cannot be taken


def test_verdict_line_offers_the_token_when_it_WOULD_help(tmp_path, capsys, monkeypatch):
    """The mirror case: a tokenless 403 is quota, and a token really does resolve it."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=_fetcher({URL: (403, None)})) == 0
    out = capsys.readouterr().out
    assert "1 of them would resolve with GITHUB_TOKEN" in out


# --- "pending on the default branch" vs "broken": the deadlock, and the five guards ---
#
# Measured on a real repo: a branch added `systems/jenkins/informes.md`, whose sibling docs link to
# it as `blob/master/systems/jenkins/informes.md`. That URL 404s until the branch merges -> 6
# `web_not_found` -> exit 4 -> red build -> **the red blocks the merge that makes the links
# resolve**. Two genuinely different states shared one kind:
#
#     will never resolve  -> a real break, must cut
#     not there YET       -> resolves on merge, and cutting blocks the merge
#
# ⚠️ THE FIRST VERSION OF THIS RUNG CHECKED ONLY TWO THINGS -- own repo, and `.exists()` -- and an
# adversarial review found FIVE ways to walk a permanently-dead link straight through it, all of
# them green. Every test below is one of those five. They are not padding: the four tests that
# shipped first (own/other/absent/no-slug) pass in ALL five leaking cases.

def _own(tmp_path, slug="example-org/handbook", ref="main"):
    from darnlink.weblinks import OwnRepo
    return OwnRepo(slug=slug, root=tmp_path, default_ref=ref)


def _git_init(tmp_path):
    """A real repo: the rung requires the destination to be a TRACKED file, so a bare tmpdir is not
    enough. `git ls-files` is what tells a file that will reach the default branch from one that
    never will (a gitignored build artefact looks identical to `.exists()`)."""
    import subprocess
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)


def test_404_on_OWN_repo_with_the_path_present_locally_is_pending_not_broken(tmp_path):
    """The deadlock case. Own repo + the path exists in the working tree -> unverifiable, gate green."""
    _w(tmp_path / "docs" / "living" / "service-topology.md", "# lives here already\n")
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    _git_init(tmp_path)
    findings, _ = check_web_links_online(tmp_path, token="tok", fetcher=_fetcher({}),
                                         own=_own(tmp_path))
    assert findings[0].kind == "web_unverifiable"
    assert "TRACKED FILE in this working tree" in findings[0].detail


def test_404_on_OWN_repo_with_the_path_ABSENT_is_still_a_real_break(tmp_path):
    """The control that keeps the rung useful: without the file there is nothing pending, so a 404
    stays exactly as broken as before. Without this test the change could silently downgrade
    everything and still look correct."""
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    _git_init(tmp_path)
    findings, _ = check_web_links_online(tmp_path, token="tok", fetcher=_fetcher({}),
                                         own=_own(tmp_path))
    assert findings[0].kind == "web_not_found"


def test_404_on_ANOTHER_repo_is_NOT_downgraded_by_a_same_named_local_file(tmp_path):
    """⚠️ THE ONE THAT MATTERS. Path-exists ALONE would silently downgrade a real break whenever an
    unrelated repo happens to share a filename -- and shared filenames are the norm, not the
    exception (`README.md`, `docs/index.md`). Only OUR OWN repo's working tree says anything about
    where a `blob/<branch>/...` URL will point after a merge; for any other repo it says nothing.
    Here the file exists locally and the link points elsewhere: it must stay `web_not_found`."""
    _w(tmp_path / "docs" / "living" / "service-topology.md", "# same path, different repo\n")
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    _git_init(tmp_path)
    findings, _ = check_web_links_online(tmp_path, token="tok", fetcher=_fetcher({}),
                                         own=_own(tmp_path, slug="someone-else/other-repo"))
    assert findings[0].kind == "web_not_found"


def test_pending_rung_is_INERT_when_the_origin_slug_is_unknown(tmp_path):
    """No `own_slug` (no origin, a non-GitHub remote, a bare tree) -> behaves exactly as before.
    A rung that changed behaviour when it could not identify the repo would be worse than no rung."""
    _w(tmp_path / "docs" / "living" / "service-topology.md", "# present\n")
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- web-uuid: {UUID} -->\n")
    _git_init(tmp_path)
    findings, _ = check_web_links_online(tmp_path, token="tok", fetcher=_fetcher({}))
    assert findings[0].kind == "web_not_found"


# --- the five leaks an adversarial review walked straight through the FIRST version of this rung ---
#
# All five were permanently-dead links that came out GREEN. None of the four tests above catches any
# of them: they all pass in every leaking case, which is why they are not enough on their own.

def test_leak1_an_immutable_ref_is_never_pending(tmp_path):
    """A `blob/<sha>/…` or `blob/<tag>/…` is IMMUTABLE: no merge makes it resolve, so calling it
    "pending on the default branch" is a lie the operator acts on. This file already carried
    `_IMMUTABLE_REF_RE` for exactly this distinction (FR-006) and the rung did not consult it. The
    fix is stronger than that regex: the ref must BE the default branch, which is what the message
    claims. A deleted long-lived branch is dead the same way and no regex would have caught it."""
    _w(tmp_path / "docs" / "living" / "service-topology.md", "# present\n")
    for ref in ("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "v1.0.0", "branch-deleted-years-ago"):
        url = f"https://github.com/example-org/handbook/blob/{ref}/docs/living/service-topology.md"
        _w(tmp_path / "conta.md", f"see [topo]({url}) <!-- web-uuid: {UUID} -->\n")
        _git_init(tmp_path)
        findings, _ = check_web_links_online(tmp_path, token="tok", fetcher=_fetcher({}),
                                             own=_own(tmp_path, ref="main"))
        assert findings[0].kind == "web_not_found", f"ref {ref!r} was forgiven"


def test_leak2_the_join_base_is_the_repo_ROOT_not_the_scanned_dir(tmp_path):
    """`gu.path` is relative to the REPO ROOT, so joining it to the SCANNED directory compares
    against the wrong tree. Not hypothetical: a fleet gate takes the scan root as an argument
    (`SCAN_ROOT="${1:-.}"`). Here the file exists under `docs/` and the URL says root-level: with the
    scanned dir as base it would "exist" and be forgiven; with the repo root it correctly stays broken."""
    url = "https://github.com/example-org/handbook/blob/main/notes.md"
    _w(tmp_path / "docs" / "notes.md", "# only under docs/\n")
    _w(tmp_path / "docs" / "conta.md", f"see [n]({url}) <!-- web-uuid: {UUID} -->\n")
    _git_init(tmp_path)
    findings, _ = check_web_links_online(tmp_path / "docs", token="tok", fetcher=_fetcher({}),
                                         own=_own(tmp_path, ref="main"))
    assert findings[0].kind == "web_not_found"


def test_leak3_a_directory_or_an_untracked_file_is_not_pending(tmp_path):
    """`.exists()` says yes to two things that NO merge can put on the default branch as a `/blob/`
    URL: a DIRECTORY (GitHub serves those under `/tree/`, so `/blob/<dir>` 404s forever) and a file
    that is not tracked (a build artefact, a gitignored report). Both looked identical to a pending
    file, and both were forgiven."""
    _w(tmp_path / ".gitignore", "dist/\n")
    _w(tmp_path / "docs" / "living" / "keep.md", "# tracked sibling so the dir exists\n")
    _w(tmp_path / "dist" / "report.html", "<p>generated</p>\n")
    _git_init(tmp_path)
    for path in ("docs/living", "dist/report.html"):
        url = f"https://github.com/example-org/handbook/blob/main/{path}"
        _w(tmp_path / "conta.md", f"see [x]({url}) <!-- web-uuid: {UUID} -->\n")
        findings, _ = check_web_links_online(tmp_path, token="tok", fetcher=_fetcher({}),
                                             own=_own(tmp_path, ref="main"))
        assert findings[0].kind == "web_not_found", f"{path!r} was forgiven"


def test_leak4_the_path_cannot_escape_the_working_tree(tmp_path):
    """`Path(root) / "/etc/hostname"` IS `/etc/hostname` in POSIX, so an absolute path in the URL
    escaped the tree entirely and `.exists()` said yes — the rung then printed that a file OUTSIDE
    the repo "EXISTS in this working tree".

    ⚠️ WHAT THIS TEST DOES AND DOES NOT PIN DOWN, because it was measured and not assumed. Seeding
    says it: remove the containment check and this test STILL PASSES. The escape is already blocked
    one guard later, by `git ls-files --error-unmatch` — nothing outside the tree is ever tracked.
    So this pins the BEHAVIOUR (an escaping path is never forgiven) and NOT which guard does it.

    The containment check stays anyway, and deliberately: it is two comparisons, it fails closed,
    and unlike the tracked check it does not depend on `git` being runnable — a subprocess that
    cannot start is exactly when you want the cheap guard to still be there. But calling it
    "the fix for this leak" would claim more than the measurement supports."""
    repo = tmp_path / "repo"
    _w(tmp_path / "vecino.md", "# outside the repo\n")
    _w(repo / "docs" / "keep.md", "# something tracked\n")
    _git_init(repo)
    for path in ("/etc/hostname", "../vecino.md"):
        url = f"https://github.com/example-org/handbook/blob/main/{path}"
        _w(repo / "conta.md", f"see [x]({url}) <!-- web-uuid: {UUID} -->\n")
        findings, _ = check_web_links_online(repo, token="tok", fetcher=_fetcher({}),
                                             own=_own(repo, ref="main"))
        assert all(f.kind != "web_unverifiable" or "TRACKED FILE" not in f.detail
                   for f in findings), f"{path!r} escaped the tree and was forgiven"


def test_leak5_a_non_ascii_slug_never_matches(tmp_path):
    """GitHub slugs are ASCII, so a lookalike is a permanently dead link — and `casefold()` COLLAPSES
    exactly those lookalikes (U+212A KELVIN folds to `k`, U+00DF to `ss`). Its sibling helper carries
    an explicit comment about `re.ASCII` and U+0131 for this same reason; the comparison did not
    inherit that hardening."""
    url = "https://github.com/example-org/handbooK/blob/main/docs/living/service-topology.md"
    _w(tmp_path / "docs" / "living" / "service-topology.md", "# present\n")
    _w(tmp_path / "conta.md", f"see [x]({url}) <!-- web-uuid: {UUID} -->\n")
    _git_init(tmp_path)
    findings, _ = check_web_links_online(tmp_path, token="tok", fetcher=_fetcher({}),
                                         own=_own(tmp_path, slug="example-org/handbook", ref="main"))
    assert findings[0].kind != "web_unverifiable" or "TRACKED FILE" not in findings[0].detail


def test_a_percent_encoded_path_still_resolves(tmp_path):
    """⚠️ NOT a leak — the opposite: the rung was INERT here. URL paths are percent-encoded, and this
    account's dominant convention puts a timezone offset in folder names (`…T104500+0200_…`), which
    in a URL is `%2B`. Undecoded, the rung silently did nothing on precisely the most common shape."""
    _w(tmp_path / "log" / "2026-08-11T104500+0200_x" / "README.md", "# pending\n")
    url = ("https://github.com/example-org/handbook/blob/main/"
           "log/2026-08-11T104500%2B0200_x/README.md")
    _w(tmp_path / "conta.md", f"see [x]({url}) <!-- web-uuid: {UUID} -->\n")
    _git_init(tmp_path)
    findings, _ = check_web_links_online(tmp_path, token="tok", fetcher=_fetcher({}),
                                         own=_own(tmp_path, ref="main"))
    assert findings[0].kind == "web_unverifiable"
    assert "TRACKED FILE" in findings[0].detail
