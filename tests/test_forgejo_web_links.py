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
    assert tried == [TS]


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
