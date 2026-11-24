"""Feature 018: web links to DECLARED self-hosted Forgejo servers are verified like GitHub's.

Every host here is under `example.test` (RFC 2606): nothing resolves, and no test touches the network
— the fetch layer is injected, or `urlopen` / `_fetch_once` are monkeypatched.
"""
import http.server
import os
import subprocess
import threading
import urllib.error
from pathlib import Path

import pytest

import darnlink.weblinks as wl
from darnlink.cli import _own_repo, _run_web_check_cli
from darnlink.weblinks import (ForgejoServer, GithubUrl, OwnRepo, check_web_links_online,
                               forgejo_identity_of_remote, parse_forgejo_servers,
                               parse_github_url)

UUID = "3f9c1a2b-4d5e-6f70-8192-a3b4c5d6e7f8"
OTHER = "11111111-2222-3333-4444-555555555555"

TS = "https://forge.example.test"
LAN = "http://forge.lan.example.test:3000"
SERVER = parse_forgejo_servers([f"{TS},{LAN}"])
FILE = f"{TS}/acme/handbook/src/branch/main/docs/a.md"
FILE_VIA_LAN = f"{LAN}/acme/handbook/src/branch/main/docs/a.md"
GH = "https://github.com/acme/handbook/blob/main/docs/a.md"

from gitenv import GIT_ENV as _GIT_ENV


@pytest.fixture(autouse=True)
def _fresh_state():
    wl._forgejo_unreachable.clear()
    wl._forgejo_repo_accessible.cache_clear()
    yield
    wl._forgejo_unreachable.clear()
    wl._forgejo_repo_accessible.cache_clear()


def _w(p: Path, text: str) -> None:
    """Bytes, not `write_text`: on Windows that turns every `\n` into `\r\n`, and the anchoring test
    compares the rewritten file byte for byte (darnlink preserves the line endings it finds)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def _with_uuid(u=UUID):
    return (200, f"---\nuuid: {u}\n---\n# dest\n")


def _fetcher(responses, calls=None):
    """Keyed by (forge key or 'github', owner/repo, ref, path). Anything unlisted 404s."""
    def f(gu: GithubUrl, token):
        key = (gu.forge.key if gu.forge else "github", f"{gu.owner}/{gu.repo}", gu.ref, gu.path)
        if calls is not None:
            calls.append((key, token))
        return responses.get(key, (404, None))
    return f


KEY = (TS, "acme/handbook", "main", "docs/a.md")


# --- declaring servers -----------------------------------------------------------------------

def test_a_declaration_is_normalised():
    (s,) = parse_forgejo_servers(["HTTPS://Forge.Example.Test:443/, http://forge.lan.example.test:3000"])
    assert s.bases == (TS, LAN)
    assert s.key == TS
    assert s.hostnames() == {"forge.example.test", "forge.lan.example.test"}


def test_a_sub_path_install_keeps_its_prefix():
    (s,) = parse_forgejo_servers(["https://example.test/git/"])
    assert s.bases == ("https://example.test/git",)


@pytest.mark.parametrize("spec", [
    "forge.example.test",                    # no scheme: refused, never guessed
    "ftp://forge.example.test",
    "https://user:pw@forge.example.test",    # credentials go in FORGEJO_TOKEN
    "https://forge.example.test/?x=1",
    "https://forge.example.test/#top",
    "https://github.com",
    "",
    "https://forge.example.test,",           # an empty alias is a typo, not nothing
    "https://forge.example.test:notaport",
    "https://forge.exa mple.test",
])
def test_a_bad_declaration_is_refused(spec):
    with pytest.raises(ValueError):
        parse_forgejo_servers([spec])


def test_a_name_declared_twice_is_refused():
    with pytest.raises(ValueError, match="twice"):
        parse_forgejo_servers([TS, f"{LAN},{TS}/"])


# --- recognising links -----------------------------------------------------------------------

def test_without_a_declaration_a_forgejo_link_is_not_recognised():
    assert parse_github_url(FILE) is None


@pytest.mark.parametrize("url, ref, kind, path", [
    (FILE, "main", "branch", "docs/a.md"),
    (FILE_VIA_LAN, "main", "branch", "docs/a.md"),
    (f"{TS}/acme/handbook/raw/branch/main/docs/a.md", "main", "branch", "docs/a.md"),
    (f"{TS}/acme/handbook/src/tag/v1.0/a.md", "v1.0", "tag", "a.md"),
    (f"{TS}/acme/handbook/src/commit/30066b0/a.md", "30066b0", "commit", "a.md"),
    (f"{TS}/acme/handbook/src/branch/main/a%2B0200.md#L3", "main", "branch", "a%2B0200.md"),
    ("https://FORGE.example.test:443/acme/handbook/src/branch/main/a.md", "main", "branch", "a.md"),
])
def test_a_declared_file_link_is_parsed(url, ref, kind, path):
    gu = parse_github_url(url, SERVER)
    assert gu is not None
    assert (gu.owner, gu.repo, gu.ref, gu.ref_kind, gu.path) == ("acme", "handbook", ref, kind, path)
    assert gu.forge == SERVER[0]
    assert gu.token_var == "FORGEJO_TOKEN"


@pytest.mark.parametrize("url", [
    "https://other.example.test/acme/handbook/src/branch/main/a.md",   # undeclared host
    "http://forge.example.test/acme/handbook/src/branch/main/a.md",    # declared https, not http
    "https://forge.example.test:3000/acme/handbook/src/branch/main/a.md",  # another port
    "http://forge.lan.example.test/acme/handbook/src/branch/main/a.md",    # declared with :3000
    f"{TS}/acme/handbook/media/branch/main/a.md",   # LFS: raw would return the pointer
    f"{TS}/acme/handbook/src/main/a.md",            # legacy form without the ref kind
    f"{TS}/acme/handbook/issues/3",
    f"{TS}/acme/handbook",
    "https://user@forge.example.test/acme/handbook/src/branch/main/a.md",
    "https://forge.example.test/acme/handbook/src/branch/main/a b.md",
])
def test_anything_else_is_not_recognised(url):
    assert parse_github_url(url, SERVER) is None


def test_a_sub_path_install_only_matches_under_its_prefix():
    servers = parse_forgejo_servers(["https://example.test/git"])
    assert parse_github_url("https://example.test/git/o/r/src/branch/main/a.md", servers).repo == "r"
    assert parse_github_url("https://example.test/o/r/src/branch/main/a.md", servers) is None
    assert parse_github_url("https://example.test/gitx/o/r/src/branch/main/a.md", servers) is None


@pytest.mark.parametrize("specs", [
    ["https://example.test,https://example.test/sub"],      # one server, root name listed first
    ["https://example.test/sub,https://example.test"],
    ["https://example.test", "https://example.test/sub"],    # two servers sharing a host
])
def test_a_sub_path_name_wins_over_a_root_name_on_the_same_host(specs):
    servers = parse_forgejo_servers(specs)
    gu = parse_github_url("https://example.test/sub/o/r/src/branch/main/a.md", servers)
    assert gu is not None and (gu.owner, gu.repo, gu.path) == ("o", "r", "a.md")
    assert "https://example.test/sub" in gu.forge.bases
    assert parse_github_url("https://example.test/o/r/src/branch/main/a.md", servers).owner == "o"


def test_github_parsing_is_unchanged_by_a_declaration():
    assert parse_github_url(GH, SERVER) == GithubUrl("acme", "handbook", "main", "docs/a.md")


def test_the_raw_api_url_is_encoded_like_the_github_one():
    gu = GithubUrl("\xf3wner", "r", "m\xe1in", "d\xf3cs/a%20b.md", forge=SERVER[0], ref_kind="branch")
    assert gu.raw_api_url(LAN) == (
        f"{LAN}/api/v1/repos/%C3%B3wner/r/raw/d%C3%B3cs/a%20b.md?ref=m%C3%A1in")


# --- verifying and anchoring -------------------------------------------------------------------

def test_a_plain_forgejo_link_is_anchored(tmp_path):
    _w(tmp_path / "x.md", f"see [a]({FILE})\n")
    findings, edits = check_web_links_online(tmp_path, None, _fetcher({KEY: _with_uuid()}),
                                             forgejo=SERVER)
    assert [f.kind for f in findings] == ["web_anchor"]
    assert edits[tmp_path / "x.md"] == f"see [a]({FILE}) <!-- web-uuid: {UUID} -->\n"


def test_an_anchored_forgejo_link_is_verified(tmp_path):
    _w(tmp_path / "ok.md", f"[a]({FILE}) <!-- web-uuid: {UUID} -->\n")
    _w(tmp_path / "bad.md", f"[a]({FILE_VIA_LAN}) <!-- web-uuid: {OTHER} -->\n")
    findings, _ = check_web_links_online(tmp_path, None, _fetcher({KEY: _with_uuid()}),
                                         forgejo=SERVER)
    assert sorted((f.file.name, f.kind) for f in findings) == [
        ("bad.md", "web_mismatch"), ("ok.md", "web_ok")]


def test_a_404_is_a_break_only_with_a_token(tmp_path):
    _w(tmp_path / "x.md", f"[a]({FILE}) <!-- web-uuid: {UUID} -->\n")
    with_token, _ = check_web_links_online(tmp_path, None, _fetcher({}), forgejo=SERVER,
                                           forgejo_token="fj")
    without, _ = check_web_links_online(tmp_path, None, _fetcher({}), forgejo=SERVER)
    assert [f.kind for f in with_token] == ["web_not_found"]
    assert [(f.kind, f.token_would_help, f.token_var) for f in without] == [
        ("web_unverifiable", True, "FORGEJO_TOKEN")]


def test_each_forge_gets_its_own_token_and_never_the_other(tmp_path):
    _w(tmp_path / "x.md", f"[a]({FILE}) and [b]({GH})\n")
    calls = []
    check_web_links_online(tmp_path, "gh-secret", _fetcher({}, calls), forgejo=SERVER,
                           forgejo_token="fj-secret")
    assert sorted(calls) == [(("github", "acme/handbook", "main", "docs/a.md"), "gh-secret"),
                             (KEY, "fj-secret")]


def test_a_github_token_alone_does_not_count_as_a_forgejo_token(tmp_path):
    _w(tmp_path / "x.md", f"[a]({FILE}) <!-- web-uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(tmp_path, "gh-secret", _fetcher({}), forgejo=SERVER)
    assert [f.kind for f in findings] == ["web_unverifiable"]


def test_a_rejected_anonymous_read_names_the_forgejo_variable(tmp_path):
    _w(tmp_path / "x.md", f"[a]({FILE})\n")
    findings, _ = check_web_links_online(tmp_path, None, _fetcher({KEY: (401, None)}),
                                         forgejo=SERVER)
    (f,) = findings
    assert f.kind == "web_unverifiable" and "FORGEJO_TOKEN" in f.detail and "60/h" not in f.detail
    assert (f.token_would_help, f.token_var) == (True, "FORGEJO_TOKEN")


@pytest.mark.parametrize("url, expected", [
    (f"{TS}/acme/handbook/src/branch/main/a.md", "web_own_no_uuid"),
    (f"{TS}/acme/handbook/src/tag/v1/a.md", "web_unverifiable"),          # FR-006: never fixable
    (f"{TS}/acme/handbook/src/commit/30066b0/a.md", "web_unverifiable"),
    (f"{TS}/acme/handbook/src/branch/30066b0/a.md", "web_unverifiable"),  # same rule as GitHub
])
def test_ownership_applies_and_immutable_refs_are_exempt(tmp_path, url, expected):
    _w(tmp_path / "x.md", f"[a]({url})\n")
    findings, _ = check_web_links_online(tmp_path, None, lambda gu, t: (200, "# no uuid\n"),
                                         owners=frozenset({"acme"}), forgejo=SERVER)
    assert [f.kind for f in findings] == [expected]


# --- the fetch layer ---------------------------------------------------------------------------

def test_the_request_goes_to_the_raw_api_with_forgejos_auth_scheme(monkeypatch):
    seen = {}

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"---\nuuid: x\n---\n"

    def fake_urlopen(req, timeout=None):
        seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
        return Resp()

    monkeypatch.setattr(wl, "_forgejo_open", lambda server, req, timeout: fake_urlopen(req, timeout))
    gu = parse_github_url(FILE, SERVER)
    assert wl._fetch_once(gu, "fj", LAN)[0] == 200
    assert seen == {"url": f"{LAN}/api/v1/repos/acme/handbook/raw/docs/a.md?ref=main",
                    "auth": "token fj"}


def test_an_unreachable_name_falls_through_and_is_remembered(monkeypatch):
    tried = []

    def once(gu, token, base=None):
        tried.append(base)
        return (-1, None) if base == TS else _with_uuid()

    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(FILE, SERVER)
    assert wl.default_fetcher(gu, None, attempts=3, sleep=lambda _s: None) == _with_uuid()
    assert tried == [TS, TS, TS, LAN]          # retried, then moved on
    tried.clear()
    assert wl.default_fetcher(gu, None, attempts=3, sleep=lambda _s: None) == _with_uuid()
    assert tried == [LAN]                      # the dead name is not paid for twice


def test_an_http_answer_is_final_and_does_not_try_another_name(monkeypatch):
    tried = []
    monkeypatch.setattr(wl, "_fetch_once", lambda gu, t, base=None: tried.append(base) or (404, None))
    gu = parse_github_url(FILE, SERVER)
    assert wl.default_fetcher(gu, None, attempts=1, sleep=lambda _s: None) == (404, None)
    assert tried == [TS, TS]                   # the slashed-ref reading `main/docs` + `a.md`, same name


# --- a branch or tag whose name holds a slash ---------------------------------------------------

SLASHED = f"{TS}/acme/handbook/raw/branch/reports/data/out/index.html"


def _only(ref, path, answer=None):
    """A `_fetch_once` that answers only for one (ref, path) reading and 404s every other."""
    tried = []

    def once(gu, token, base=None):
        tried.append((gu.ref, gu.path))
        return (answer or _with_uuid()) if (gu.ref, gu.path) == (ref, path) else (404, None)
    return once, tried


def test_a_branch_with_a_slash_is_found_by_lengthening_the_ref(monkeypatch):
    once, tried = _only("reports/data", "out/index.html")
    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(SLASHED, SERVER)
    assert (gu.ref, gu.path) == ("reports", "data/out/index.html")   # the parse alone cannot know
    assert wl.default_fetcher(gu, "fj", attempts=3, sleep=lambda _s: None) == _with_uuid()
    assert tried[-2:] == [("reports", "data/out/index.html"), ("reports/data", "out/index.html")]


def test_a_tag_with_a_slash_is_found_too(monkeypatch):
    once, _ = _only("v1/rc", "docs/a.md")
    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(f"{TS}/acme/handbook/src/tag/v1/rc/docs/a.md", SERVER)
    assert wl.default_fetcher(gu, None, attempts=1, sleep=lambda _s: None) == _with_uuid()


def test_a_commit_link_is_never_re_split(monkeypatch):
    tried = []
    monkeypatch.setattr(wl, "_fetch_once", lambda gu, t, base=None: tried.append(gu.ref) or (404, None))
    gu = parse_github_url(f"{TS}/acme/handbook/raw/commit/0123abcd/docs/a.md", SERVER)
    assert wl.default_fetcher(gu, None, attempts=1, sleep=lambda _s: None) == (404, None)
    assert tried == ["0123abcd"]


def test_the_extra_readings_are_bounded_and_not_retried(monkeypatch):
    tried = []
    monkeypatch.setattr(wl, "_fetch_once", lambda gu, t, base=None: tried.append(gu.ref) or (404, None))
    gu = parse_github_url(f"{TS}/acme/handbook/raw/branch/b/1/2/3/4/5/6/7/x.md", SERVER)
    assert wl.default_fetcher(gu, None, attempts=3, sleep=lambda _s: None) == (404, None)
    # 3 tries of the parsed reading (404 is transient for the retry loop), then ONE per longer ref
    assert tried == ["b"] * 3 + ["b/1", "b/1/2", "b/1/2/3", "b/1/2/3/4"]


def test_a_real_404_with_a_slashed_reading_still_reaches_the_repo_probe(monkeypatch):
    monkeypatch.setattr(wl, "_fetch_once", lambda gu, t, base=None: (404, None))
    monkeypatch.setattr(wl, "_forgejo_repo_accessible", lambda s, b, o, r, t: False)
    gu = parse_github_url(SLASHED, SERVER)
    assert wl.default_fetcher(gu, "fj", attempts=1, sleep=lambda _s: None) == (-2, None)


def test_a_flaky_answer_on_the_right_reading_is_retried(monkeypatch):
    answers = iter([(502, None), (-1, None), _with_uuid()])
    tried = []

    def once(gu, token, base=None):
        tried.append(gu.ref)
        return next(answers) if gu.ref == "reports/data" else (404, None)

    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(SLASHED, SERVER)
    assert wl.default_fetcher(gu, "fj", attempts=3, sleep=lambda _s: None) == _with_uuid()
    assert tried == ["reports"] * 3 + ["reports/data"] * 3
    assert TS not in wl._forgejo_unreachable    # the name answered: one blip does not bury it


def test_a_one_segment_path_has_no_other_reading(monkeypatch):
    tried = []
    monkeypatch.setattr(wl, "_fetch_once", lambda gu, t, base=None: tried.append(gu.ref) or (404, None))
    gu = parse_github_url(f"{TS}/acme/handbook/raw/branch/main/a.md", SERVER)
    assert wl.default_fetcher(gu, None, attempts=1, sleep=lambda _s: None) == (404, None)
    assert tried == ["main"]


def test_a_non_404_on_a_longer_reading_is_that_readings_answer(monkeypatch):
    once, _ = _only("reports/data", "out/index.html", answer=(403, None))
    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(SLASHED, SERVER)
    assert wl.default_fetcher(gu, None, attempts=1, sleep=lambda _s: None) == (403, None)


def test_every_name_unreachable_is_a_network_error(monkeypatch):
    monkeypatch.setattr(wl, "_fetch_once", lambda gu, t, base=None: (-1, None))
    gu = parse_github_url(FILE, SERVER)
    assert wl.default_fetcher(gu, None, attempts=1, sleep=lambda _s: None) == (-1, None)


def test_a_404_in_a_repo_the_token_cannot_read_is_ambiguous(monkeypatch):
    monkeypatch.setattr(wl, "_fetch_once", lambda gu, t, base=None: (404, None))
    gu = parse_github_url(FILE, SERVER)
    monkeypatch.setattr(wl, "_forgejo_repo_accessible", lambda s, b, o, r, t: False)
    assert wl.default_fetcher(gu, "fj", attempts=1, sleep=lambda _s: None) == (-2, None)
    monkeypatch.setattr(wl, "_forgejo_repo_accessible", lambda s, b, o, r, t: True)
    assert wl.default_fetcher(gu, "fj", attempts=1, sleep=lambda _s: None) == (404, None)


def test_repo_probe_maps_404_to_not_readable(monkeypatch):
    def boom(server, req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
    monkeypatch.setattr(wl, "_forgejo_open", boom)
    assert wl._forgejo_repo_accessible(SERVER[0], TS, "acme", "handbook", "fj") is False


# --- this repo on a Forgejo: pending on the default branch ------------------------------------

@pytest.mark.parametrize("remote, expected", [
    ("https://forge.example.test/acme/Handbook.git", (TS, "acme/handbook")),
    ("ssh://git@forge.lan.example.test:2222/acme/handbook.git", (TS, "acme/handbook")),
    ("git@forge.example.test:acme/handbook.git", (TS, "acme/handbook")),
    ("https://forge.example.test/git/acme/handbook/", (TS, "acme/handbook")),
    ("https://github.com/acme/handbook.git", None),
    ("https://other.example.test/acme/handbook.git", None),
    ("https://forge.example.test/handbook", None),
])
def test_a_remote_on_a_declared_server_identifies_the_repo(remote, expected):
    assert forgejo_identity_of_remote(remote, SERVER) == expected


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, env=_GIT_ENV, capture_output=True)


def _repo_with_tracked_file(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=_GIT_ENV)
    _w(tmp_path / "docs" / "a.md", "---\nuuid: " + UUID + "\n---\n")
    _git(tmp_path, "add", "docs/a.md")
    return tmp_path


def test_a_404_to_a_tracked_file_of_this_repo_on_the_forgejo_is_pending(tmp_path):
    root = _repo_with_tracked_file(tmp_path)
    _git(root, "remote", "add", "origin", "https://github.com/someone/else.git")
    _git(root, "remote", "add", "forge", "ssh://git@forge.lan.example.test:2222/acme/handbook.git")
    own = _own_repo(root, "main", SERVER)
    assert own is not None and own.forgejo_slugs == {(TS, "acme/handbook")}
    _w(root / "x.md", f"[a]({FILE}) <!-- web-uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(root, None, _fetcher({}), forgejo=SERVER,
                                         forgejo_token="fj", own=own)
    (f,) = [f for f in findings if f.file.name == "x.md"]
    assert f.kind == "web_unverifiable" and "pending" in f.detail


def test_origin_itself_may_be_the_forgejo(tmp_path):
    root = _repo_with_tracked_file(tmp_path)
    _git(root, "remote", "add", "origin", "https://forge.example.test/acme/handbook.git")
    own = _own_repo(root, "main", SERVER)
    assert own is not None and own.slug == "" and own.forgejo_slugs == {(TS, "acme/handbook")}
    assert _own_repo(root, "main") is None       # without a declaration: exactly as before


@pytest.mark.parametrize("own_slugs, url", [
    (frozenset(), FILE),                                            # same slug, but no remote there
    (frozenset({(TS, "acme/handbook")}), f"{TS}/acme/handbook/src/tag/main/docs/a.md"),
    (frozenset({(TS, "acme/handbook")}), f"{TS}/acme/handbook/src/branch/dev/docs/a.md"),
])
def test_what_is_not_pending_stays_broken(tmp_path, own_slugs, url):
    root = _repo_with_tracked_file(tmp_path)
    # The GitHub slug matches on purpose: it must not vouch for a repo on another forge.
    own = OwnRepo(slug="acme/handbook", root=root, default_ref="main", forgejo_slugs=own_slugs)
    _w(root / "x.md", f"[a]({url}) <!-- web-uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(root, None, _fetcher({}), forgejo=SERVER,
                                         forgejo_token="fj", own=own)
    assert [f.kind for f in findings if f.file.name == "x.md"] == ["web_not_found"]


# --- a link to a FOLDER is judged by its README.md, as locally ---------------------------------
# Forgejo's raw API answers 404 for a path that is a directory. Locally a folder link is anchored to
# its README.md (feature 011); the same link written as a URL must not read as missing.

FOLDER = f"{TS}/acme/handbook/src/branch/main/docs/kit"
FOLDER_README = (TS, "acme/handbook", "main", "docs/kit/README.md")


def _no_sleep_fetcher(gu, token):
    """`default_fetcher` with one attempt and no sleeps, so the end-to-end tests run the real
    folder retry against a monkeypatched `_fetch_once`."""
    return wl.default_fetcher(gu, token, attempts=1, sleep=lambda _s: None)


def _answers(responses):
    """A `_fetch_once` keyed like `_fetcher`, recording every reading it is asked for."""
    tried = []

    def once(gu, token, base=None):
        key = (gu.forge.key, f"{gu.owner}/{gu.repo}", gu.ref, gu.path)
        tried.append(key)
        return responses.get(key, (404, None))
    return once, tried


def test_a_folder_link_is_fetched_through_its_readme(monkeypatch):
    once, tried = _answers({FOLDER_README: _with_uuid()})
    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(FOLDER, SERVER)
    assert wl.default_fetcher(gu, "fj", attempts=3, sleep=lambda _s: None) == _with_uuid()
    # the file readings first (unchanged), then the folder readings, the README one answering
    assert tried[:3] == [(TS, "acme/handbook", "main", "docs/kit")] * 3
    assert tried[-1] == FOLDER_README


@pytest.mark.parametrize("anchor, kind", [(f" <!-- web-uuid: {UUID} -->", "web_ok"),
                                          (f" <!-- web-uuid: {OTHER} -->", "web_mismatch"),
                                          ("", "web_anchor")])
def test_a_folder_link_takes_the_uuid_of_its_readme(tmp_path, monkeypatch, anchor, kind):
    once, _ = _answers({FOLDER_README: _with_uuid()})
    monkeypatch.setattr(wl, "_fetch_once", once)
    _w(tmp_path / "x.md", f"see [kit]({FOLDER}){anchor}\n")
    findings, edits = check_web_links_online(tmp_path, None, _no_sleep_fetcher, forgejo=SERVER,
                                             forgejo_token="fj")
    assert [f.kind for f in findings] == [kind]
    if kind == "web_anchor":
        assert findings[0].anchored_uuid == UUID
        assert edits[tmp_path / "x.md"] == f"see [kit]({FOLDER}) <!-- web-uuid: {UUID} -->\n"


def test_a_trailing_slash_does_not_double_it(monkeypatch):
    once, tried = _answers({FOLDER_README: _with_uuid()})
    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(FOLDER + "/", SERVER)
    assert wl.default_fetcher(gu, "fj", attempts=1, sleep=lambda _s: None) == _with_uuid()
    assert all("//" not in path for *_, path in tried)


def test_a_folder_on_a_slashed_branch_is_found_on_the_longer_reading(monkeypatch):
    once, tried = _answers({(TS, "acme/handbook", "reports/data", "kit/README.md"): _with_uuid()})
    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(f"{TS}/acme/handbook/src/branch/reports/data/kit", SERVER)
    assert wl.default_fetcher(gu, "fj", attempts=1, sleep=lambda _s: None) == _with_uuid()
    assert [p for *_, p in tried] == ["data/kit", "kit", "data/kit/README.md", "kit/README.md"]


@pytest.mark.parametrize("token, accessible, expected", [
    ("fj", True, (404, None)),       # a folder without a README.md: broken, exactly as before
    ("fj", False, (-2, None)),       # ...and the repo probe still runs after the folder readings
    (None, True, (404, None)),       # no token: the 404 is still handed on for `_classify`
])
def test_a_folder_without_a_readme_is_judged_as_before(monkeypatch, token, accessible, expected):
    once, tried = _answers({})
    monkeypatch.setattr(wl, "_fetch_once", once)
    monkeypatch.setattr(wl, "_forgejo_repo_accessible", lambda s, b, o, r, t: accessible)
    gu = parse_github_url(FOLDER, SERVER)
    assert wl.default_fetcher(gu, token, attempts=1, sleep=lambda _s: None) == expected
    # one request per folder reading, none of them retried: a broken link stays cheap
    assert [p for *_, p in tried] == ["docs/kit", "kit", "docs/kit/README.md", "kit/README.md"]


def test_a_folder_without_a_readme_is_still_web_not_found(tmp_path, monkeypatch):
    once, _ = _answers({})
    monkeypatch.setattr(wl, "_fetch_once", once)
    monkeypatch.setattr(wl, "_forgejo_repo_accessible", lambda s, b, o, r, t: True)
    _w(tmp_path / "x.md", f"[kit]({FOLDER}) <!-- web-uuid: {UUID} -->\n")
    with_token, _ = check_web_links_online(tmp_path, None, _no_sleep_fetcher, forgejo=SERVER,
                                           forgejo_token="fj")
    without, _ = check_web_links_online(tmp_path, None, _no_sleep_fetcher, forgejo=SERVER)
    assert [f.kind for f in with_token] == ["web_not_found"]
    assert [(f.kind, f.token_would_help) for f in without] == [("web_unverifiable", True)]


@pytest.mark.parametrize("answer", [(403, None), (401, None), (502, None), (-1, None)])
def test_only_a_200_on_the_readme_replaces_the_404(monkeypatch, answer):
    once, _ = _answers({FOLDER_README: answer})
    monkeypatch.setattr(wl, "_fetch_once", once)
    monkeypatch.setattr(wl, "_forgejo_repo_accessible", lambda s, b, o, r, t: True)
    gu = parse_github_url(FOLDER, SERVER)
    assert wl.default_fetcher(gu, "fj", attempts=1, sleep=lambda _s: None) == (404, None)


def test_a_flaky_readme_is_retried(monkeypatch):
    answers = iter([(502, None), _with_uuid()])
    tried = []

    def once(gu, token, base=None):
        tried.append(gu.path)
        return next(answers) if gu.path == "docs/kit/README.md" else (404, None)

    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(FOLDER, SERVER)
    assert wl.default_fetcher(gu, "fj", attempts=3, sleep=lambda _s: None) == _with_uuid()
    assert tried.count("docs/kit/README.md") == 2


@pytest.mark.parametrize("url", [FILE, f"{TS}/acme/handbook/src/branch/main/docs/README.md",
                                 f"{TS}/acme/handbook/src/branch/main/docs/A.MD"])
def test_a_markdown_file_link_never_asks_for_a_readme(monkeypatch, url):
    once, tried = _answers({})
    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(url, SERVER)
    assert wl.default_fetcher(gu, None, attempts=1, sleep=lambda _s: None) == (404, None)
    assert not any(p.endswith("/README.md") and p != gu.path for *_, p in tried)
    assert len(tried) == 2                     # the parsed reading and its one longer reading


def test_a_file_that_answers_is_never_asked_as_a_folder(monkeypatch):
    once, tried = _answers({KEY: _with_uuid()})
    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(FILE, SERVER)
    assert wl.default_fetcher(gu, None, attempts=1, sleep=lambda _s: None) == _with_uuid()
    assert tried == [KEY]


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_read_is_never_asked_as_a_folder(monkeypatch, status):
    once, tried = _answers({(TS, "acme/handbook", "main", "docs/kit"): (status, None),
                            FOLDER_README: _with_uuid()})
    monkeypatch.setattr(wl, "_fetch_once", once)
    gu = parse_github_url(FOLDER, SERVER)
    assert wl.default_fetcher(gu, "fj", attempts=1, sleep=lambda _s: None) == (status, None)
    assert tried == [(TS, "acme/handbook", "main", "docs/kit")]


def test_github_is_not_asked_for_a_folder_readme(monkeypatch):
    """GitHub's Contents API answers a directory with 200 and a JSON listing, not with a 404, and
    GitHub writes folder URLs as `/tree/`, which is not parsed: the folder retry is Forgejo's."""
    tried = []
    monkeypatch.setattr(wl, "_fetch_once", lambda gu, t, base=None: tried.append(gu.path) or (404, None))
    monkeypatch.setattr(wl, "_repo_accessible", lambda o, r, t: True)
    gu = parse_github_url("https://github.com/acme/handbook/blob/main/docs/kit")
    assert wl.default_fetcher(gu, "gh", attempts=1, sleep=lambda _s: None) == (404, None)
    assert tried == ["docs/kit"]


def _repo_with_folder(tmp_path, readme=True, track=True):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=_GIT_ENV)
    _w(tmp_path / "docs" / "kit" / "notes.txt", "tracked sibling so the folder exists\n")
    _git(tmp_path, "add", "docs/kit/notes.txt")
    if readme:
        _w(tmp_path / "docs" / "kit" / "README.md", "---\nuuid: " + UUID + "\n---\n")
        if track:
            _git(tmp_path, "add", "docs/kit/README.md")
    return tmp_path


def _own_on_forge(root):
    return OwnRepo(slug="", root=root, default_ref="main",
                   forgejo_slugs=frozenset({(TS, "acme/handbook")}))


def test_a_404_to_a_folder_of_this_repo_with_a_tracked_readme_is_pending(tmp_path):
    root = _repo_with_folder(tmp_path)
    _w(root / "x.md", f"[kit]({FOLDER}) <!-- web-uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(root, None, _fetcher({}), forgejo=SERVER,
                                         forgejo_token="fj", own=_own_on_forge(root))
    (f,) = [f for f in findings if f.file.name == "x.md"]
    assert f.kind == "web_unverifiable" and "pending" in f.detail
    assert "is a folder whose `README.md` is a TRACKED FILE" in f.detail


@pytest.mark.parametrize("readme, track", [(False, False), (True, False)])
def test_a_folder_whose_readme_is_absent_or_untracked_is_not_pending(tmp_path, readme, track):
    root = _repo_with_folder(tmp_path, readme=readme, track=track)
    _w(root / "x.md", f"[kit]({FOLDER}) <!-- web-uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(root, None, _fetcher({}), forgejo=SERVER,
                                         forgejo_token="fj", own=_own_on_forge(root))
    assert [f.kind for f in findings if f.file.name == "x.md"] == ["web_not_found"]


def test_a_folder_named_like_markdown_is_not_pending(tmp_path):
    """The fetch never asks `x.md/README.md`, so the rung must not promise it will resolve."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=_GIT_ENV)
    _w(tmp_path / "docs" / "odd.md" / "README.md", "---\nuuid: " + UUID + "\n---\n")
    _git(tmp_path, "add", "docs/odd.md/README.md")
    _w(tmp_path / "x.md", f"[o]({TS}/acme/handbook/src/branch/main/docs/odd.md) <!-- web-uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(tmp_path, None, _fetcher({}), forgejo=SERVER,
                                         forgejo_token="fj", own=_own_on_forge(tmp_path))
    assert [f.kind for f in findings if f.file.name == "x.md"] == ["web_not_found"]


def test_a_github_folder_of_this_repo_is_still_not_pending(tmp_path):
    """Only the Forgejo fetch asks for the README, so only there does a merge resolve the folder."""
    root = _repo_with_folder(tmp_path)
    _w(root / "x.md",
       f"[kit](https://github.com/acme/handbook/blob/main/docs/kit) <!-- web-uuid: {UUID} -->\n")
    own = OwnRepo(slug="acme/handbook", root=root, default_ref="main")
    findings, _ = check_web_links_online(root, "gh", _fetcher({}), own=own)
    assert [f.kind for f in findings if f.file.name == "x.md"] == ["web_not_found"]


# --- the command line --------------------------------------------------------------------------

def test_forgejo_needs_online(tmp_path, capsys):
    assert _run_web_check_cli([str(tmp_path), "--forgejo", TS]) == 1
    assert "--online" in capsys.readouterr().err


def test_a_bad_declaration_is_a_usage_error(tmp_path, capsys):
    assert _run_web_check_cli([str(tmp_path), "--online", "--forgejo", "forge.example.test"]) == 1
    assert "scheme" in capsys.readouterr().err


def test_end_to_end_through_the_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGEJO_TOKEN", "fj")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _w(tmp_path / "x.md", f"[a]({FILE_VIA_LAN}) <!-- web-uuid: {OTHER} -->\n")
    calls = []
    rc = _run_web_check_cli([str(tmp_path), "--online", "--forgejo", f"{TS},{LAN}"],
                            fetcher=_fetcher({KEY: _with_uuid()}, calls))
    assert rc == 4 and "web_mismatch" in capsys.readouterr().out
    assert calls == [(KEY, "fj")]


def test_the_summary_names_the_variable_that_would_help(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FORGEJO_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _w(tmp_path / "x.md", f"[a]({FILE}) <!-- web-uuid: {UUID} -->\n")
    rc = _run_web_check_cli([str(tmp_path), "--online", "--forgejo", TS], fetcher=_fetcher({}))
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 of them would resolve with FORGEJO_TOKEN" in out and "GITHUB_TOKEN" not in out


# --- redirects must not carry the token off the declared names ---------------------------------
# Real sockets, loopback only: the leak lives inside urllib's redirect handling, and a mocked
# `urlopen` would skip exactly the code under test.

def _serve(handler_body):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            handler_body(self)
        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _recorder(seen):
    def body(h):
        seen.append(h.headers.get("Authorization"))
        h.send_response(200)
        h.end_headers()
        h.wfile.write(b"---\nuuid: " + UUID.encode() + b"\n---\n")
    return body


def _redirector(location):
    def body(h):
        h.send_response(302)
        h.send_header("Location", location)
        h.end_headers()
    return body


@pytest.mark.parametrize("probe", ["file", "repo"])
def test_a_redirect_to_an_undeclared_host_does_not_get_the_token(probe):
    seen = []
    target = _serve(_recorder(seen))
    source = _serve(_redirector(f"http://127.0.0.1:{target.server_port}/elsewhere"))
    try:
        servers = parse_forgejo_servers([f"http://127.0.0.1:{source.server_port}"])
        gu = parse_github_url(f"http://127.0.0.1:{source.server_port}/o/r/src/branch/main/a.md",
                              servers)
        if probe == "file":
            assert wl._fetch_once(gu, "SECRET")[0] == 200
        else:
            wl._forgejo_repo_accessible(servers[0], servers[0].key, "o", "r", "SECRET")
        assert seen == [None]
    finally:
        source.shutdown(); target.shutdown()


def test_a_redirect_between_declared_names_keeps_the_token():
    seen = []
    target = _serve(_recorder(seen))
    source = _serve(_redirector(f"http://127.0.0.1:{target.server_port}/api/v1/x"))
    try:
        servers = parse_forgejo_servers(
            [f"http://127.0.0.1:{source.server_port},http://127.0.0.1:{target.server_port}"])
        gu = parse_github_url(f"http://127.0.0.1:{source.server_port}/o/r/src/branch/main/a.md",
                              servers)
        status, text = wl._fetch_once(gu, "SECRET")
        assert status == 200 and UUID in text
        assert seen == ["token SECRET"]
    finally:
        source.shutdown(); target.shutdown()
