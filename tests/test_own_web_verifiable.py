"""Feature 021: with `--own-verifiable`, an OWNED destination that could not be read fails.

One test per acceptance scenario of `specs/021-own-web-verifiable/spec.md`, in order. The fetch layer
is mocked everywhere, as in the 016 suite (`tests/test_own_repo_web_strictness.py`): no test touches
the network. Every host is either github.com, never contacted, or under `example.test`.
"""
import json
from pathlib import Path

import pytest

import darnlink.weblinks as wl
from darnlink.cli import _run_web_check_cli
from darnlink.weblinks import GithubUrl, check_web_links_online, parse_forgejo_servers

UUID = "3f9c1a2b-4d5e-6f70-8192-a3b4c5d6e7f8"

OWNED = "https://github.com/owned/repo/blob/main/docs/a.md"
FOREIGN = "https://github.com/someone-else/repo/blob/main/docs/a.md"

FORGE = "https://forge.example.test"
SERVER = parse_forgejo_servers([FORGE])
FJ_OWNED = f"{FORGE}/owned/handbook/src/branch/main/docs/a.md"


@pytest.fixture(autouse=True)
def _no_ambient_tokens(monkeypatch):
    """A developer's or a CI agent's own token must not decide what these tests see: the token is an
    input of the classification, so each test sets the one it means."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("FORGEJO_TOKEN", raising=False)
    wl._forgejo_unreachable.clear()
    yield
    wl._forgejo_unreachable.clear()


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def _fetcher(responses, calls=None):
    """Keyed by the href as written (GitHub blob URL, or a Forgejo src URL). Unlisted -> 404."""
    def f(gu: GithubUrl, token):
        if gu.forge is not None:
            key = f"{gu.forge.key}/{gu.owner}/{gu.repo}/src/branch/{gu.ref}/{gu.path}"
        else:
            key = f"https://github.com/{gu.owner}/{gu.repo}/blob/{gu.ref}/{gu.path}"
        if calls is not None:
            calls.append(key)
        return responses.get(key, (404, None))
    return f


def _kinds(tmp_path, fetch, token=None, owners=frozenset({"owned"}), own_verifiable=True, **kw):
    findings, _ = check_web_links_online(tmp_path, token, fetch, owners=owners,
                                         own_verifiable=own_verifiable, **kw)
    return [f.kind for f in findings], findings


# 1
def test_an_owned_destination_that_cannot_be_read_fails_and_says_how_to_fix_it(tmp_path, capsys):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    kinds, findings = _kinds(tmp_path, _fetcher({}))
    assert kinds == ["web_own_unverifiable"]
    detail = findings[0].detail
    assert "owned/repo" in detail and "docs/a.md" in detail      # which destination
    assert "404 without a token" in detail                       # the cause
    assert "GITHUB_TOKEN" in detail                              # what provisioning fixes it
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-verifiable"],
                              fetcher=_fetcher({})) == 4
    assert "[web_own_unverifiable]" in capsys.readouterr().out


# 2
def test_without_the_flag_nothing_changes(tmp_path, capsys):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    kinds, _ = _kinds(tmp_path, _fetcher({}), own_verifiable=False)
    assert kinds == ["web_unverifiable"]
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned"],
                              fetcher=_fetcher({})) == 0
    assert "own-unverifiable" not in capsys.readouterr().out     # summary line unchanged


# 3
def test_a_destination_you_do_not_own_stays_informational(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({FOREIGN})\n")
    kinds, _ = _kinds(tmp_path, _fetcher({}))
    assert kinds == ["web_unverifiable"]
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-verifiable"],
                              fetcher=_fetcher({})) == 0


# 4
@pytest.mark.parametrize("url", [
    "https://github.com/owned/repo/pull/3",          # a PR page
    "https://github.com/owned/repo/issues/7",        # an issue
    "https://github.com/owned/repo",                 # a repository home page
    f"{FORGE}/owned/handbook/pulls/12",              # a PR page on a declared Forgejo
])
def test_a_url_that_is_not_a_file_link_stays_informational_even_on_an_owned_host(tmp_path, url):
    _w(tmp_path / "src.md", f"see [x]({url})\n")
    calls = []
    kinds, _ = _kinds(tmp_path, _fetcher({}, calls), forgejo=SERVER)
    assert kinds == ["web_unverifiable"]
    assert calls == []                               # not a file link: nothing to read, nothing read
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-verifiable",
                               "--forgejo", FORGE], fetcher=_fetcher({})) == 0


# 5
def test_the_flag_without_an_owner_set_is_a_usage_error(tmp_path, capsys):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    calls = []
    assert _run_web_check_cli([str(tmp_path), "--online", "--own-verifiable"],
                              fetcher=_fetcher({}, calls)) == 1
    assert "--own-verifiable needs an owner set" in capsys.readouterr().err
    assert calls == []


def test_the_flag_without_online_is_a_usage_error(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    calls = []
    assert _run_web_check_cli([str(tmp_path), "--own", "owned", "--own-verifiable"],
                              fetcher=_fetcher({}, calls)) == 1
    assert calls == []


# 6
@pytest.mark.parametrize("resp,token,cause", [
    ((401, None), None, "anonymous request rejected (401)"),
    ((403, None), None, "anonymous request rejected (403)"),
    ((403, None), "tok", "was rejected (403)"),
    ((-2, None), "tok", "cannot read"),
    ((404, None), None, "404 without a token"),
    ((-1, None), "tok", "network failure"),
    ((502, None), "tok", "status 502"),
])
def test_every_way_of_not_reading_an_owned_destination_fails(tmp_path, resp, token, cause):
    """Anchored, so the link is the one a gate relies on: an anchor nobody can verify is not one."""
    _w(tmp_path / "src.md", f"see [x]({OWNED}) <!-- web-uuid: {UUID} -->\n")
    kinds, findings = _kinds(tmp_path, _fetcher({OWNED: resp}), token=token)
    assert kinds == ["web_own_unverifiable"]
    assert cause in findings[0].detail


# 7
@pytest.mark.parametrize("resp,token,kind", [
    ((404, None), "tok", "web_not_found"),              # a readable repo answered: an answer, not a failure
    ((-3, None), None, "web_unverifiable"),             # a malformed URL: no token fixes it
    ((200, "# no frontmatter\n"), None, "web_own_no_uuid"),   # read fine: 016's finding, not this one
    ((200, f"---\nuuid: {UUID}\n---\n"), None, "web_anchor"),  # read fine: anchorable, exit 3
])
def test_what_was_answered_keeps_its_classification(tmp_path, resp, token, kind):
    """No double counting: a status this rung does not own keeps exactly today's kind."""
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    kinds, _ = _kinds(tmp_path, _fetcher({OWNED: resp}), token=token)
    assert kinds == [kind]


# 8
def test_a_declared_forgejo_names_its_own_variable(tmp_path):
    """018 FR-008: the advice names the variable that would fix it, and Forgejo's is not GitHub's."""
    _w(tmp_path / "src.md", f"see [x]({FJ_OWNED})\n")
    kinds, findings = _kinds(tmp_path, _fetcher({}), forgejo=SERVER)
    assert kinds == ["web_own_unverifiable"]
    assert "FORGEJO_TOKEN" in findings[0].detail and "GITHUB_TOKEN" not in findings[0].detail
    assert "owned/handbook" in findings[0].detail


def test_an_unreachable_forgejo_names_the_server(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({FJ_OWNED})\n")
    kinds, findings = _kinds(tmp_path, _fetcher({FJ_OWNED: (-1, None)}), forgejo=SERVER,
                             forgejo_token="tok")
    assert kinds == ["web_own_unverifiable"]
    assert FORGE in findings[0].detail


# 9
@pytest.mark.parametrize("marker", ["<!-- darnlink-ignore-file -->", "<!-- darnlink-ignore-links -->"])
def test_a_file_level_opt_out_keeps_it_informational(tmp_path, marker):
    _w(tmp_path / "src.md", f"{marker}\n\nsee [x]({OWNED})\n")
    kinds, _ = _kinds(tmp_path, _fetcher({}))
    assert kinds == ["web_unverifiable"]


# 10
def test_an_exempt_link_still_has_to_be_readable(tmp_path):
    """016's marker exempts three verdicts reached on a 200; status decides first, here as there."""
    _w(tmp_path / "src.md", f"see [x]({OWNED}) <!-- darnlink-own-exempt -->\n")
    kinds, _ = _kinds(tmp_path, _fetcher({}))
    assert kinds == ["web_own_unverifiable"]


# 11
def test_the_016_budget_does_not_cover_it(tmp_path):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    assert _run_web_check_cli([str(tmp_path), "--online", "--own", "owned", "--own-verifiable",
                               "--own-max", "5"], fetcher=_fetcher({})) == 4


# 12
def test_it_reaches_json_and_the_text_report(tmp_path, capsys):
    _w(tmp_path / "src.md", f"see [x]({OWNED})\n")
    args = [str(tmp_path), "--online", "--own", "owned", "--own-verifiable"]
    _run_web_check_cli(args + ["--json"], fetcher=_fetcher({}))
    out = json.loads(capsys.readouterr().out)
    assert out["exit_code"] == 4 and out["web_own_unverifiable"] == 1 and out["own_verifiable"] is True
    assert [f["kind"] for f in out["findings"]] == ["web_own_unverifiable"]

    _run_web_check_cli(args, fetcher=_fetcher({}))
    text = capsys.readouterr().out
    assert "own-unverifiable 1" in text and "integrity failure" in text


# 13
def test_it_costs_no_extra_fetch(tmp_path):
    _w(tmp_path / "src.md", f"a [x]({OWNED})\nb [y]({FOREIGN})\n")
    plain, flagged = [], []
    _kinds(tmp_path, _fetcher({}, plain), own_verifiable=False)
    _kinds(tmp_path, _fetcher({}, flagged))
    assert plain == flagged and len(flagged) == 2
