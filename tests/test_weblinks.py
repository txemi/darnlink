"""Feature 010 (EXPERIMENTAL spike): cross-repo web-link robustness, ONLINE-fetch design.

Network is never touched: every test injects a fake `fetcher` mapping a GithubUrl -> (status, text),
so the fetch layer is exercised deterministically. Demonstrates the chosen design on the real case
(txconta -> txnet1 by GitHub URL anchored to the destination's uuid): anchor a plain web link, verify
an anchored one, fail on mismatch/404, stay honest (web_unverifiable) on a private repo with no token,
and never fire in the core / offline mode.
"""
import hashlib
import json
from pathlib import Path

import pytest

from darnlink.cli import _run_web_check_cli, main
from darnlink.weblinks import (GithubUrl, check_web_links_online, find_web_links,
                               parse_github_url)

UUID = "3f9c1a2b-4d5e-6f70-8192-a3b4c5d6e7f8"
OTHER = "11111111-2222-3333-4444-555555555555"
URL = "https://github.com/txemi/txnet1/blob/main/projects/software/homelab/docs_vivos/jenkins_topologia.md"


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
    assert parse_github_url("https://github.com/txemi/txnet1/blob/main/a/b/c.md") == \
        GithubUrl("txemi", "txnet1", "main", "a/b/c.md")


def test_parse_raw_and_www():
    assert parse_github_url("https://www.github.com/o/r/raw/dev/x.md") == GithubUrl("o", "r", "dev", "x.md")


def test_parse_non_github_is_none():
    assert parse_github_url("https://example.com/foo") is None
    assert parse_github_url("https://gitlab.com/o/r/-/blob/main/x.md") is None


def test_contents_api_url():
    gu = GithubUrl("txemi", "txnet1", "main", "docs/x.md")
    assert gu.contents_api_url() == \
        "https://api.github.com/repos/txemi/txnet1/contents/docs/x.md?ref=main"


# --- link finder: robust vs plain web links, code fences ignored ---

def test_find_web_links_plain_and_anchored():
    content = (f"a [p]({URL})\n"
               f"b [q]({URL}) <!-- uuid: {UUID} -->\n"
               "c [local](x.md)\n")
    links = find_web_links(content)
    assert [l.uuid for l in links] == [None, UUID]


def test_find_web_links_skips_code_fence():
    content = f"```\n[x]({URL}) <!-- uuid: {UUID} -->\n```\n"
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
    assert f"<!-- uuid: {UUID} -->" in edits[tmp_path / "conta.md"]
    # dry-run must not touch disk
    assert (tmp_path / "conta.md").read_text() == f"see [topo]({URL})\n"


def test_online_anchor_applied_with_write(tmp_path, capsys):
    _w(tmp_path / "conta.md", f"see [topo]({URL})\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {UUID}\n---\n")})
    code = _run_web_check_cli([str(tmp_path), "--online", "--write", "--json"], fetcher=fetch)
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["wrote"] == 1
    assert (tmp_path / "conta.md").read_text() == f"see [topo]({URL}) <!-- uuid: {UUID} -->\n"


def test_online_anchor_pending_exits_3(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL})\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {UUID}\n---\n")})
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch) == 3  # dry-run, anchor pending


# --- ONLINE: verify an already-anchored link ---

def test_online_verify_match_web_ok(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {UUID}\n---\n")})
    findings, edits = check_web_links_online(tmp_path, None, fetch)
    assert [f.kind for f in findings] == ["web_ok"]
    assert edits == {}


def test_online_verify_mismatch_exits_4(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {OTHER}\n---\n")})  # destination uuid differs
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch) == 4


def test_online_dest_has_no_uuid_is_mismatch(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (200, "# a destination with no frontmatter\n")})
    findings, _ = check_web_links_online(tmp_path, None, fetch)
    assert findings[0].kind == "web_mismatch"


# --- failure cases: 404, private-no-token, unparseable, network error ---

def test_online_404_is_web_not_found_exits_4(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- uuid: {UUID} -->\n")
    fetch = _fetcher({})  # every URL -> 404
    findings, _ = check_web_links_online(tmp_path, None, fetch)
    assert findings[0].kind == "web_not_found"
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch) == 4


def test_online_private_no_token_is_unverifiable(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (403, None)})  # private repo, no token -> 403
    findings, _ = check_web_links_online(tmp_path, token=None, fetcher=fetch)
    assert findings[0].kind == "web_unverifiable"
    assert "no GITHUB_TOKEN" in findings[0].detail
    # unverifiable does not fail the exit (not a broken link, just unconfirmed)
    assert _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch) == 0


def test_online_private_with_token_reads_uuid(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- uuid: {UUID} -->\n")

    def fetch(gu, token):  # 403 without token, 200 with it
        return (200, f"---\nuuid: {UUID}\n---\n") if token else (403, None)

    findings, _ = check_web_links_online(tmp_path, token="ghp_fake", fetcher=fetch)
    assert findings[0].kind == "web_ok"


def test_online_network_error_is_unverifiable(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (-1, None)})  # URLError/timeout mapped to -1
    findings, _ = check_web_links_online(tmp_path, None, fetch)
    assert findings[0].kind == "web_unverifiable"


def test_online_unparseable_url_is_unverifiable(tmp_path):
    _w(tmp_path / "conta.md", f"see [x](https://example.com/whatever) <!-- uuid: {UUID} -->\n")
    findings, _ = check_web_links_online(tmp_path, None, _fetcher({}))
    assert findings[0].kind == "web_unverifiable"


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
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- uuid: {UUID} -->\n")  # uuid not local
    assert main([str(tmp_path)]) == 0                 # repair: web link inert
    assert main([str(tmp_path), "--robustify"]) == 0  # robustify: not a local .md
    assert main(["check", str(tmp_path)]) == 0        # check: both axes clean


# --- report-only unless --write: verify path never mutates disk ---

def test_verify_never_writes(tmp_path):
    _w(tmp_path / "conta.md", f"see [topo]({URL}) <!-- uuid: {UUID} -->\n")
    fetch = _fetcher({URL: (200, f"---\nuuid: {OTHER}\n---\n")})
    before = _checksums(tmp_path)
    _run_web_check_cli([str(tmp_path), "--online"], fetcher=fetch)  # mismatch, but read-only
    assert _checksums(tmp_path) == before


def test_bad_flag_exits_1(tmp_path):
    with pytest.raises(SystemExit) as e:
        _run_web_check_cli([str(tmp_path), "--nonexistent"])
    assert e.value.code == 1
