"""Tests for the `recipes/darnlink-gate` bash recipe — the create-readme axis under mode=check and
the per-axis `create_readme_excludes` key (the two changes for repos with a big `mirrors/` tree).

The recipe shells out to `uvx --from <ref> darnlink …`. To run offline (and fast) we put a tiny `uvx`
SHIM on PATH that drops the `--from <ref> darnlink` prefix and execs the locally installed `darnlink`
console script instead (the same one CI installs via `uv pip install -e .`). No network, no version pin.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parent.parent / "recipes" / "darnlink-gate"

U = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _darnlink_bin() -> str | None:
    return shutil.which("darnlink") or (
        str(Path(sys.executable).parent / "darnlink")
        if (Path(sys.executable).parent / "darnlink").exists()
        else None
    )


pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win")
    or os.name == "nt"
    or shutil.which("bash") is None
    or _darnlink_bin() is None
    or shutil.which("git") is None,
    # The recipe under test is the POSIX `recipes/darnlink-gate` bash script; Windows ships the separate
    # `darnlink-gate.ps1`, which these tests do not exercise.
    reason="recipe gate tests need a POSIX shell (bash) + git + the installed darnlink console script",
)

# env keys that would otherwise leak an outer CI/user config into the recipe under test
_LEAKY_ENV = (
    "DARNLINK_REF", "DARNLINK_GATE_MODE", "DARNLINK_GATE_SCOPE", "DARNLINK_GATE_FAIL_CLOSED",
    "DARNLINK_GATE_WEB", "DARNLINK_GATE_CREATE_README", "DARNLINK_GATE_TOKEN_FILE",
    "DARNLINK_GATE_DANGLING", "DARNLINK_GATE_DANGLING_MAX",
    "DARNLINK_GATE_OWN_WEB_FROM_ORIGIN", "DARNLINK_GATE_OWN_WEB_MAX",
    "DARNLINK_GATE_INCLUDE_MERMAID",
    # ⚠️ And git's own. `git` exports these to every hook it runs, so when this suite is executed
    # FROM the repo's pre-commit hook (`tools/check.sh`), an un-scrubbed `git` in a test inherits
    # GIT_DIR from the outer repo while using the sandbox as its work tree. That combination is not
    # a failing test — it is a `git add -A` against the wrong repository. It committed "delete
    # every tracked file" into a real branch here on 2026-08-09 before this scrubbing existed.
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_INDEX_VERSION",
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
)


def _clean_env() -> dict:
    """The ambient environment minus anything that would point a subprocess at the outer repo."""
    return {k: v for k, v in os.environ.items() if k not in _LEAKY_ENV}


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run git INSIDE `repo`, never inheriting the caller's git environment (see _LEAKY_ENV)."""
    return subprocess.run(["git", *args], cwd=repo, env=_clean_env(), check=check,
                          capture_output=True, text=True)


@pytest.fixture
def sandbox(tmp_path):
    """A git-init'd repo dir + a `run(config)` helper that writes darnlink-gate.json and runs the recipe."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")

    bindir = tmp_path / "shimbin"
    bindir.mkdir()
    shim = bindir / "uvx"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'args=("$@")\n'
        '[ "${args[0]:-}" = "--from" ] && args=("${args[@]:2}")\n'   # drop `--from <ref>`
        '[ "${args[0]:-}" = "darnlink" ] && args=("${args[@]:1}")\n'  # drop the tool name
        # Record the argv when asked. A WIRING test cannot assert on the verdict: without a token the
        # destination is unverifiable and the gate exits 0 whether or not the flag was passed — which
        # is exactly how a dropped `--own` survived mutation until this existed.
        '[ -n "${DARNLINK_ARGV_LOG:-}" ] && printf \'%s\\n\' "$*" >> "$DARNLINK_ARGV_LOG"\n'
        'exec "${DARNLINK_BIN:-darnlink}" "${args[@]}"\n'
    )
    shim.chmod(0o755)

    def run(config: dict, argv_log: Path | None = None, uvx_dir: Path | None = None,
            extra_env: dict | None = None) -> subprocess.CompletedProcess:
        (repo / "darnlink-gate.json").write_text(json.dumps(config))
        env = _clean_env()
        if argv_log is not None:
            env["DARNLINK_ARGV_LOG"] = str(argv_log)
        if extra_env:
            env.update(extra_env)
        env["PATH"] = f"{uvx_dir or bindir}{os.pathsep}" + env.get("PATH", "")
        env["DARNLINK_BIN"] = _darnlink_bin()
        return subprocess.run(
            ["bash", str(RECIPE)], cwd=repo, env=env, capture_output=True, text=True
        )

    return repo, run


def _dir_link_without_readme(repo: Path) -> None:
    """A note with a plain link to a folder that has NO README (so no uuid to anchor the dir-link to)."""
    (repo / "docs").mkdir()
    (repo / "docs" / "page.md").write_text("# page\n")
    (repo / "A.md").write_text("# A\nSee [the docs](docs/) for more.\n")


def _robustifiable_link_inside(repo: Path, folder: str) -> None:
    """A plain link (inside `folder`) to a target that already carries a uuid → a strict/robustify offender."""
    (repo / "T.md").write_text(f"---\nuuid: {U}\n---\n# T\n")
    (repo / folder / "inner.md").write_text("# inner\nsee [t](../T.md) plain\n")


# --- (a) create_readme now works under mode=check, not only mode=max --------------------------------

def test_check_alone_ignores_a_dirlink_to_a_folder_without_readme(sandbox):
    """Baseline: `mode=check` (integrity + strict) does NOT flag a dir-link to a README-less folder."""
    repo, run = sandbox
    _dir_link_without_readme(repo)
    r = run({"ref": "x", "mode": "check"})
    assert r.returncode == 0, r.stderr


def test_check_plus_create_readme_fails_on_missing_readme(sandbox):
    """The change: with create_readme=true, that same dir-link fails the gate UNDER mode=check."""
    repo, run = sandbox
    _dir_link_without_readme(repo)
    r = run({"ref": "x", "mode": "check", "create_readme": True})
    assert r.returncode != 0, "create_readme under check must fail on a README-less dir-link"
    assert "create-readme" in r.stderr.lower()


# --- (b) create_readme_excludes applies to the create-readme pass ONLY ------------------------------

def test_create_readme_excludes_suppresses_the_axis(sandbox):
    """Excluding the folder from the create-readme pass makes the gate green again."""
    repo, run = sandbox
    _dir_link_without_readme(repo)
    r = run({"ref": "x", "mode": "check", "create_readme": True, "create_readme_excludes": ["docs"]})
    assert r.returncode == 0, r.stderr
    assert "[create-readme]" not in r.stderr


def test_create_readme_excludes_do_not_disable_robustify_over_that_folder(sandbox):
    """create_readme_excludes must bite ONLY the create-readme axis — integrity/robustify must still
    validate links that live inside the excluded folder (a mirror still gets its inbound links checked)."""
    repo, run = sandbox
    _dir_link_without_readme(repo)
    _robustifiable_link_inside(repo, "docs")
    r = run({"ref": "x", "mode": "check", "create_readme": True, "create_readme_excludes": ["docs"]})
    assert r.returncode == 3, f"strict/robustify should still fire inside the excluded dir; got {r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[create-readme]" not in r.stderr  # the create-readme axis itself is suppressed for docs


# --- (b-bis) the WEB pass must not swallow the axes that come after it ------------------------------

def test_web_pass_does_not_skip_the_create_readme_axis(sandbox):
    """REGRESSION. The web pass used to end in a bare `exit "$rc"`, which left the script before the
    create-readme axis further down. In a repo with `mode=max` + `web: true` + `create_readme_excludes`
    the axis therefore NEVER RAN: the config said it was on, the gate said exit 0, and a directory link
    to a folder with no README sailed through. Measured on two consuming repos before the fix — same
    tree, same config, `web` on → 0, `web` off → 1.

    Offline-safe: the sandbox has no GitHub links, so `web-check --online` returns 0 without touching
    the network. What is under test is the FALL-THROUGH, not the web check itself.
    """
    repo, run = sandbox
    _dir_link_without_readme(repo)
    cfg = {"ref": "x", "mode": "max", "web": True,
           "create_readme": True, "create_readme_excludes": ["nothing-to-exclude"]}
    r = run(cfg)
    assert r.returncode != 0, (
        "with web on, the create-readme axis must still run and fail; "
        f"got {r.returncode}\n{r.stdout}\n{r.stderr}"
    )
    assert "no README" in r.stderr, r.stderr


def test_web_pass_verdict_survives_the_later_axes(sandbox):
    """The other half of the same change: falling through must not DOWNGRADE a web failure. A later
    axis that finds nothing must leave the web verdict intact (the axes only ever raise rc from 0)."""
    repo, run = sandbox
    (repo / "A.md").write_text("# A\nnothing to see\n")
    r = run({"ref": "x", "mode": "max", "web": True, "create_readme": True,
             "create_readme_excludes": ["nothing-to-exclude"]})
    assert r.returncode == 0, f"clean tree must stay green\n{r.stdout}\n{r.stderr}"


def test_a_127_during_the_web_pass_still_bails(tmp_path):
    """The ceiling of RC_IS_FINAL. web-check's codes are 0..4 and none means "unreachable", so a 4 is a
    final verdict — but a code ABOVE the contract (127 = tool missing, 126 = permissions) is not a verdict
    about the repo at all, and must still go through bail(): fail-open SKIPS, fail-closed exits 4.

    Caught by Copilot on PR #45: the first draft skipped the heuristic whenever RC_IS_FINAL was set, so a
    machine without `uv` would have got a hard 127 out of a gate that promises to fail open.

    The shim answers normally for every pass and dies with 127 only for `web-check`, which is exactly the
    narrow window: the core passed, then the tool became unreachable.
    """
    repo = tmp_path / "repo"; repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "A.md").write_text("# A\n")
    bindir = tmp_path / "shimbin"; bindir.mkdir()
    shim = bindir / "uvx"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'args=("$@")\n'
        '[ "${args[0]:-}" = "--from" ] && args=("${args[@]:2}")\n'
        '[ "${args[0]:-}" = "darnlink" ] && args=("${args[@]:1}")\n'
        '[ "${args[0]:-}" = "web-check" ] && { echo "boom" >&2; exit 127; }\n'
        'exec "${DARNLINK_BIN:-darnlink}" "${args[@]}"\n'
    )
    shim.chmod(0o755)
    (repo / "darnlink-gate.json").write_text(json.dumps(
        {"ref": "x", "mode": "max", "web": True, "create_readme": True,
         "create_readme_excludes": ["nothing-to-exclude"]}))
    env = _clean_env(); env["PATH"] = f"{bindir}{os.pathsep}" + env.get("PATH", "")
    env["DARNLINK_BIN"] = _darnlink_bin()

    r = subprocess.run(["bash", str(RECIPE)], cwd=repo, env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"fail-open must SKIP on an unreachable tool, not surface 127\n{r.stderr}"
    assert "SKIP" in r.stderr or "unreachable" in r.stderr, r.stderr

    env["DARNLINK_GATE_FAIL_CLOSED"] = "1"
    r2 = subprocess.run(["bash", str(RECIPE)], cwd=repo, env=env, capture_output=True, text=True)
    assert r2.returncode == 4, f"fail-closed must exit 4 (could-not-gate), got {r2.returncode}\n{r2.stderr}"


# --- (c) backward compatibility: mode=max without the new key is unchanged --------------------------

def test_backward_compat_max_without_create_readme_is_green(sandbox):
    """mode=max with create_readme OFF: a README-less dir-link is not a create-readme offender."""
    repo, run = sandbox
    _dir_link_without_readme(repo)
    assert run({"ref": "x", "mode": "max"}).returncode == 0


def test_backward_compat_max_with_folded_create_readme_still_fails(sandbox):
    """mode=max + create_readme (NO create_readme_excludes) keeps the legacy FOLDED behavior: the
    create-readme flag rides inside the max robustify pass and the README-less dir-link fails the gate,
    exactly as before this change."""
    repo, run = sandbox
    _dir_link_without_readme(repo)
    r = run({"ref": "x", "mode": "max", "create_readme": True})
    assert r.returncode != 0, "max + create_readme must still fail on a README-less dir-link"


# --- an unavailable create-readme axis must never mask a failing core gate --------------------------

def test_unavailable_create_readme_axis_does_not_mask_a_failing_core(tmp_path):
    """The OPTIONAL create-readme pass needs python3 to filter its JSON by kind. If python3 is missing,
    the pass can't run — but that must NOT turn an ALREADY-failing core gate (integrity/strict) green.
    We simulate python3-missing with a minimal PATH and assert the core strict failure (exit 3) survives."""
    needed = {}
    for t in ("bash", "git", "mktemp", "rm", "tr", "env"):
        p = shutil.which(t)
        if p is None:
            pytest.skip(f"need {t} for this test")
        needed[t] = p
    # `realpath`/`dirname` are needed by neither the recipe nor this test: they are needed by the
    # `darnlink` binary the test injects. Built by `uv run`, that binary is a Python-shebang script
    # and needs neither; built by `uvx`, it is a /bin/sh wrapper whose first lines call both. Omit
    # them and the wrapper dies with 127, the recipe takes its designed "can't run darnlink -> SKIP"
    # path, and this test fails claiming the GATE returned 0 when the FIXTURE never ran it. That
    # matters more here than it would elsewhere: `uvx` is how the tool is actually consumed, so a
    # fixture that only works under `uv run` is blind in the mode that ships.
    #
    # BEST-EFFORT ON PURPOSE, unlike the six above: a host missing them can still run this test
    # whenever its injected binary does not need them, so requiring them would trade a real failure
    # for a silent skip -- and losing coverage quietly is the failure mode this whole file exists to
    # prevent. If they are missing AND the binary needs them, the probe below says so out loud.
    for t in ("realpath", "dirname"):
        p = shutil.which(t)
        if p is not None:
            needed[t] = p
    dbin = _darnlink_bin()

    repo = tmp_path / "repo"
    repo.mkdir()
    # `env=_clean_env()`, like every other git call here: run from the repo's own pre-commit hook,
    # an inherited GIT_DIR would make this init/operate on the OUTER repository. The absolute path
    # is kept because this test deliberately builds a minimal PATH later.
    subprocess.run([needed["git"], "init", "-q"], cwd=repo, env=_clean_env(), check=True)
    # a plain link to a uuid'd target → a strict/robustify offender → the core `check` exits 3
    (repo / "T.md").write_text(f"---\nuuid: {U}\n---\n# T\n")
    (repo / "A.md").write_text("# A\n[t](T.md) plain\n")
    (repo / "darnlink-gate.json").write_text("{}")

    bindir = tmp_path / "nopybin"  # a PATH with the recipe's tools but NO python3
    bindir.mkdir()
    for t, p in needed.items():
        os.symlink(p, bindir / t)
    shim = bindir / "uvx"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'args=("$@")\n'
        '[ "${args[0]:-}" = "--from" ] && args=("${args[@]:2}")\n'
        '[ "${args[0]:-}" = "darnlink" ] && args=("${args[@]:1}")\n'
        'exec "${DARNLINK_BIN:-darnlink}" "${args[@]}"\n'
    )
    shim.chmod(0o755)

    env = _clean_env()
    env["PATH"] = str(bindir)  # only the minimal bin → python3 is unreachable
    env["DARNLINK_BIN"] = dbin
    env["DARNLINK_GATE_MODE"] = "check"
    env["DARNLINK_GATE_CREATE_README"] = "1"  # request the axis via env (no python3 to read the json)
    # sanity: python3 really is unreachable through this PATH
    assert subprocess.run([needed["bash"], "-c", "command -v python3"], env=env,
                          capture_output=True).returncode != 0
    # sanity, the other half: the injected binary must still RUN through this PATH. The premise
    # above was asserted from the start and this one was not, which is why an environment shift
    # surfaced as "the gate returned 0" -- a claim about the product -- instead of "my fixture is
    # broken". A test may narrow the world it runs in; it must not lie about which half gave way.
    # `--help` and not `--version`: darnlink has no `--version`, and a probe that fails for its
    # OWN reason would be the very confusion this assert exists to remove.
    probe = subprocess.run([dbin, "--help"], env=env, capture_output=True, text=True)
    assert probe.returncode == 0, (
        f"the injected darnlink cannot run under this minimal PATH, so the gate below would be "
        f"skipped rather than exercised:\n{probe.stderr}")

    r = subprocess.run([needed["bash"], str(RECIPE)], cwd=repo, env=env, capture_output=True, text=True)
    assert r.returncode == 3, (
        f"core strict failure must survive an unavailable create-readme axis; got {r.returncode}\n"
        f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    )


# --- (c) the dangling axis (015) and its added-lines ratchet ----------------------------------------
#
# The rung that makes this adoptable. Every consumer already carries years of dangling links, so an
# axis that gates the whole repo on day one would be bypassed, not fixed. `added-lines` judges only
# what the commit ADDS: old debt never blocks, new debt cannot enter.

def _commit(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", msg)


def _repo_with_old_debt(repo: Path) -> None:
    """A committed file that already contains a link to a path that never existed."""
    (repo / "doc.md").write_text(f"---\nuuid: {U}\n---\n\n# doc\n\n[old debt](gone.md)\n")
    _commit(repo, "base")


def test_dangling_is_off_by_default(sandbox):
    """The ratchet rule: upgrading the pin must not change any verdict for a repo that did not opt in.

    `check` still states the count on one line — a repo should learn it has dead links — but it must
    not enumerate them (a consumer measured at 2,526 would drown its real findings) and it must not
    move the exit code.
    """
    repo, run = sandbox
    _repo_with_old_debt(repo)

    r = run({})   # no `dangling` key at all
    out = r.stdout + r.stderr

    assert r.returncode == 0
    assert "gone.md" not in out          # not enumerated
    assert "does not affect the exit code" in out   # but not hidden either


def test_added_lines_lets_old_debt_through(sandbox):
    """Touching a file that carries old danglers must not block the commit."""
    repo, run = sandbox
    _repo_with_old_debt(repo)
    (repo / "doc.md").write_text((repo / "doc.md").read_text() + "\nan added line with no links\n")
    _git(repo, "add", "doc.md")

    r = run({"dangling": "added-lines", "scope": "staged"})

    assert r.returncode == 0, r.stdout + r.stderr


def test_added_lines_blocks_a_newly_added_dead_link(sandbox):
    """The other half: what the commit introduces is judged, and named with its line."""
    repo, run = sandbox
    _repo_with_old_debt(repo)
    (repo / "doc.md").write_text((repo / "doc.md").read_text() + "\n[brand new](never_existed.md)\n")
    _git(repo, "add", "doc.md")

    r = run({"dangling": "added-lines", "scope": "staged"})

    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "never_existed.md" in out
    assert "gone.md" not in out          # the old debt is still none of this commit's business


def test_warn_reports_without_failing(sandbox):
    """The honest way to see the backlog before gating it."""
    repo, run = sandbox
    _repo_with_old_debt(repo)
    (repo / "doc.md").write_text((repo / "doc.md").read_text() + "\n[brand new](never_existed.md)\n")
    _git(repo, "add", "doc.md")

    r = run({"dangling": "warn", "scope": "staged"})

    assert r.returncode == 0, r.stdout + r.stderr
    assert "never_existed.md" in (r.stdout + r.stderr)


def test_repo_scope_fails_on_any_dangling_link(sandbox):
    """The wall, for a repo already at zero."""
    repo, run = sandbox
    _repo_with_old_debt(repo)

    r = run({"dangling": "repo"})

    assert r.returncode != 0
    assert "gone.md" in (r.stdout + r.stderr)


# --- (c-bis) `dangling_max`: the budget that makes `repo` adoptable before you reach zero ----------
#
# Without it there is no rung between `added-lines` and `repo`, and `added-lines` needs a staged diff
# — so a repo carrying old debt has NO server-side dangling wall at all until the day it hits exactly
# zero. The budget buys the wall today and ratchets down with each cleanup.

def _repo_with_n_danglers(repo: Path, n: int) -> None:
    """A committed file carrying exactly `n` links to paths that never existed."""
    body = "".join(f"[d{i}](gone{i}.md)\n\n" for i in range(n))
    (repo / "doc.md").write_text(f"---\nuuid: {U}\n---\n\n# doc\n\n{body}")
    _commit(repo, "base")


def test_budget_defaults_to_zero_so_an_upgrade_changes_no_verdict(sandbox):
    """No `dangling_max` key must behave exactly as before: `repo` fails on any finding."""
    repo, run = sandbox
    _repo_with_n_danglers(repo, 2)

    r = run({"dangling": "repo"})

    assert r.returncode != 0
    # and it must not start talking about a budget nobody set. Match the phrases, not the bare word:
    # the sandbox path carries this test's name, so "budget" appears in every line of output.
    out = r.stdout + r.stderr
    assert "the budget" not in out
    assert "dangling_max" not in out


def test_count_over_the_budget_still_fails_and_names_the_budget(sandbox):
    repo, run = sandbox
    _repo_with_n_danglers(repo, 2)

    r = run({"dangling": "repo", "dangling_max": 1})

    assert r.returncode != 0
    assert "over the budget of 1" in (r.stdout + r.stderr)


def test_count_at_the_budget_passes(sandbox):
    """The whole point: a repo with known debt gets a real wall at its current number."""
    repo, run = sandbox
    _repo_with_n_danglers(repo, 2)

    r = run({"dangling": "repo", "dangling_max": 2})

    assert r.returncode == 0, r.stdout + r.stderr
    assert "exactly at the budget" in (r.stdout + r.stderr)


def test_coming_in_under_budget_asks_for_the_budget_to_be_lowered(sandbox):
    """A budget that is never lowered is an allowance. Nothing else would notice it went stale, so
    the gate has to say it here — in front of whoever just did the cleanup."""
    repo, run = sandbox
    _repo_with_n_danglers(repo, 2)

    r = run({"dangling": "repo", "dangling_max": 5})

    assert r.returncode == 0, r.stdout + r.stderr
    assert "lower dangling_max to 2" in (r.stdout + r.stderr)


def test_reaching_zero_with_a_budget_still_asks_for_it_to_be_dropped(sandbox):
    """The milestone case, and the one that is easiest to get wrong.

    If the reminder lives inside `there are findings`, the gate goes SILENT exactly when the last
    dangler dies — the one moment the stale budget is both visible and free to remove. A ratchet
    whose reminder disappears on success is not a ratchet, it is an allowance with a grace period.
    """
    repo, run = sandbox
    _repo_with_n_danglers(repo, 0)   # a clean repo: the cleanup finished

    r = run({"dangling": "repo", "dangling_max": 5})

    assert r.returncode == 0, r.stdout + r.stderr
    assert "drop dangling_max" in (r.stdout + r.stderr)


def test_a_clean_repo_without_a_budget_says_nothing(sandbox):
    """The mirror of the above: no budget set, nothing to nag about."""
    repo, run = sandbox
    _repo_with_n_danglers(repo, 0)

    r = run({"dangling": "repo"})

    assert r.returncode == 0, r.stdout + r.stderr
    assert "dangling_max" not in (r.stdout + r.stderr)


def test_a_junk_budget_is_treated_as_zero_not_as_infinite(sandbox):
    """A typo must never silently WIDEN an allowance — it fails closed, and says why."""
    repo, run = sandbox
    _repo_with_n_danglers(repo, 2)

    r = run({"dangling": "repo", "dangling_max": "muchos"})

    assert r.returncode != 0
    assert "not a non-negative integer" in (r.stdout + r.stderr)


def test_budget_does_not_leak_into_the_warn_rung(sandbox):
    """Only `repo` has a wall, so a budget there must not turn `warn` into something that fails."""
    repo, run = sandbox
    _repo_with_n_danglers(repo, 2)

    r = run({"dangling": "warn", "dangling_max": 1})

    assert r.returncode == 0, r.stdout + r.stderr


def test_staged_scope_survives_a_payload_bigger_than_one_env_var(sandbox):
    """Regression: the payload must not travel through the environment.

    Linux caps a SINGLE env var (or argv entry) at MAX_ARG_STRLEN = 32 pages = 128 KiB — a per-string
    limit, separate from the ~2 MB ARG_MAX total. Exceeding it makes the next `exec` fail with E2BIG,
    so the gate does not report a finding, it *crashes*: `sed: Argument list too long`, exit 126. A
    gate that cannot run gates nothing.

    A whole-repo `check --json` on a real consumer measured ~200 KB. This builds a comparable payload
    from a single file so the test stays fast.
    """
    repo, run = sandbox
    links = "\n".join(f"[dead {i}](missing_target_with_a_deliberately_long_name_{i}.md)"
                      for i in range(1200))
    (repo / "big.md").write_text(f"---\nuuid: {U}\n---\n\n{links}\n")
    _commit(repo, "base")
    (repo / "big.md").write_text((repo / "big.md").read_text() + "\ntail line\n")
    _git(repo, "add", "big.md")

    # Assert the PRECONDITION, or this stops being a regression test the day the payload shrinks
    # (a shorter `detail`, a leaner JSON shape) and silently starts passing for the wrong reason.
    limit = os.sysconf("SC_PAGESIZE") * 32          # MAX_ARG_STRLEN, in bytes
    payload = subprocess.run([_darnlink_bin(), "check", str(repo), "--json"],
                             capture_output=True, text=True, env=_clean_env()).stdout
    assert len(payload) > limit, (
        f"scenario no longer reproduces the bug: payload is {len(payload)} B, "
        f"under the {limit} B per-string limit. Make it bigger or delete this test."
    )

    r = run({"dangling": "added-lines", "scope": "staged"})
    out = r.stdout + r.stderr

    assert "Argument list too long" not in out, out[:400]
    assert r.returncode == 0, out[:400]   # the added line carries no link → nothing to gate on


# --- own_web: the feature-016 keys (a list of owners, a boolean, and a budget) ---

def _owned_web_link_without_uuid(repo: Path) -> None:
    """A plain web link to a `.md` in a repo we will claim as ours, whose destination has no uuid.
    The gate never reaches the network in these tests: `web-check` is the shimmed local darnlink, and
    without a token a destination it cannot read is `web_unverifiable`, exit 0. What is exercised here
    is the WIRING — that the keys reach the CLI at all — not the classification, which lives in
    tests/test_own_repo_web_strictness.py."""
    (repo / "A.md").write_text(
        "# A\nsee [x](https://github.com/owned/repo/blob/main/a.md) plain\n")


def test_own_web_max_without_own_web_is_a_config_error_not_a_verdict(sandbox):
    """Feature 016 makes exit 1 reachable from CONFIGURATION. Reported as a red gate it would send
    someone hunting for broken links that do not exist; routed to `bail()` it would EXIT the script
    and skip every axis after it — the bug this pass already fixed once. It warns, drops the axis, and
    lets the rest of the gate speak."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)

    r = run({"mode": "max", "web": True, "own_web_max": 5})

    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "CONFIG" in out and "did NOT run" in out


def test_a_junk_own_web_max_is_ignored_not_treated_as_infinite(sandbox):
    """Silently WIDENING an allowance is the one direction a config typo must not be able to go —
    the same rule `dangling_max` follows. Ignored, and said out loud."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)

    r = run({"mode": "max", "web": True, "own_web": ["owned"], "own_web_max": "muchos"})

    assert "not a non-negative integer" in (r.stdout + r.stderr)


def test_own_web_is_a_list_so_an_owner_called_origin_stays_expressible(sandbox):
    """`own_web_from_origin` is its own key rather than a sentinel inside the list, for the same
    reason the CLI has a flag instead of `--own auto`: an owner literally called `origin` must remain
    a legal input. Here it is passed as a plain owner and the gate accepts it."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)

    r = run({"mode": "max", "web": True, "own_web": ["origin", "owned"]})

    out = r.stdout + r.stderr
    assert "CONFIG error" not in out, out       # not rejected as a bad argument
    assert r.returncode == 0, out


def test_the_keys_do_nothing_when_the_web_axis_is_off(sandbox, tmp_path):
    """`own_web` rides on `web`. With the axis off the pass must not run at all — asserted on the
    INVOCATION, because the exit code cannot tell: a destination nobody can read is unverifiable and
    the gate exits 0 whether or not web-check ran."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)
    log = tmp_path / "argv.log"

    r = run({"mode": "max", "own_web": ["owned"], "own_web_max": 0}, argv_log=log)

    assert r.returncode == 0, r.stdout + r.stderr
    assert not [l for l in log.read_text().splitlines() if "web-check" in l], log.read_text()


def test_the_owner_keys_actually_reach_the_cli(sandbox, tmp_path):
    """The wiring itself, asserted on the INVOCATION rather than the verdict. Without a token the
    destination is unverifiable and the gate exits 0 whether or not the flags were passed, so a
    verdict-based test cannot tell — and did not: dropping the `--own` loop entirely left every other
    test in this file green."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)
    log = tmp_path / "argv.log"

    run({"mode": "max", "web": True, "own_web": ["owned", "other"],
         "own_web_from_origin": True, "own_web_max": 3}, argv_log=log)

    web = [l for l in log.read_text().splitlines() if "web-check" in l]
    assert web, log.read_text()
    assert "--own owned" in web[0] and "--own other" in web[0]
    assert "--own-from-origin" in web[0]
    assert "--own-max 3" in web[0]


def test_absent_keys_leave_the_command_line_untouched(sandbox, tmp_path):
    """The rule every key in this recipe follows: not opting in changes nothing for you."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)
    log = tmp_path / "argv.log"

    run({"mode": "max", "web": True}, argv_log=log)

    web = [l for l in log.read_text().splitlines() if "web-check" in l]
    assert web and "--own" not in web[0], web


def test_an_exit_1_is_NOT_swallowed_for_a_repo_that_never_opted_in(sandbox, tmp_path):
    """The blocking defect this pass shipped with: the swallow was unconditional, so ANY exit 1 —
    `uvx` failing on its own, an uncaught Python exception — turned green for every consumer with
    `web: true`, including those who never adopted 016. Worse than before the key existed."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)
    fake = tmp_path / "exit1bin"
    fake.mkdir()
    (fake / "uvx").write_text('#!/usr/bin/env bash\ncase " $* " in *" web-check "*) exit 1;; esac\n'
                              'args=("$@"); [ "${args[0]:-}" = "--from" ] && args=("${args[@]:2}")\n'
                              '[ "${args[0]:-}" = "darnlink" ] && args=("${args[@]:1}")\n'
                              'exec "${DARNLINK_BIN:-darnlink}" "${args[@]}"\n')
    (fake / "uvx").chmod(0o755)

    r = run({"mode": "max", "web": True}, uvx_dir=fake)   # no own_* keys at all

    assert r.returncode == 1, r.stdout + r.stderr


def test_under_fail_closed_a_config_error_is_not_a_pass(sandbox, tmp_path):
    """In CI the gate IS the wall: an axis that could not run must not read as one that ran clean.
    Fail-open drops it with a warning; fail-closed makes it 4 — and the later axes still execute,
    because bail() would exit the script and skip them."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)

    r = run({"mode": "max", "web": True, "own_web_max": 5, "fail_closed": True})

    assert r.returncode == 4, r.stdout + r.stderr
    assert "not a pass" in (r.stdout + r.stderr)


def test_an_explicit_zero_budget_reaches_the_cli(sandbox, tmp_path):
    """`own_web_max: 0` is the value whose distinction from "absent" is the whole point of FR-012, and
    it was the one not covered: a mutation that dropped the explicit 0 survived the suite."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)
    log = tmp_path / "argv.log"

    run({"mode": "max", "web": True, "own_web": ["owned"], "own_web_max": 0}, argv_log=log)

    web = [l for l in log.read_text().splitlines() if "web-check" in l]
    assert web and "--own-max 0" in web[0], web


def test_the_env_overrides_win_over_the_json(sandbox, tmp_path, monkeypatch):
    """Both new env keys were added to the leak-scrub list and then never exercised: renaming either
    one in the recipe left the whole suite green."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)
    log = tmp_path / "argv.log"

    run({"mode": "max", "web": True, "own_web": ["owned"], "own_web_max": 3}, argv_log=log,
        extra_env={"DARNLINK_GATE_OWN_WEB_MAX": "9", "DARNLINK_GATE_OWN_WEB_FROM_ORIGIN": "1"})

    web = [l for l in log.read_text().splitlines() if "web-check" in l]
    assert web and "--own-max 9" in web[0] and "--own-from-origin" in web[0], web


def test_own_web_configured_where_the_pass_never_runs_says_so(sandbox):
    """Configured under mode=check the rule simply does not apply, and a no-op that reads like
    protection is what the CLI itself refuses to be."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)

    r = run({"mode": "check", "web": True, "own_web": ["owned"]})

    assert "NOT being applied" in (r.stdout + r.stderr)


def _uvx_forcing_web_check_to(tmp_path, code: int) -> Path:
    """A uvx shim that makes ONLY the web pass exit with `code` and lets every other subcommand
    through — the only way to exercise the recipe's reading of a code the real tool will not produce
    on demand."""
    d = tmp_path / f"uvx{code}"
    d.mkdir()
    (d / "uvx").write_text(
        f'#!/usr/bin/env bash\ncase " $* " in *" web-check "*) exit {code};; esac\n'
        'args=("$@"); [ "${args[0]:-}" = "--from" ] && args=("${args[@]:2}")\n'
        '[ "${args[0]:-}" = "darnlink" ] && args=("${args[@]:1}")\n'
        'exec "${DARNLINK_BIN:-darnlink}" "${args[@]}"\n')
    (d / "uvx").chmod(0o755)
    return d


@pytest.mark.parametrize("cfg", [
    {"mode": "max", "web": True, "own_web": ["me"]},
    {"mode": "max", "web": True, "own_web_from_origin": True},
    {"mode": "max", "web": True, "own_web_max": 5},
])
def test_each_own_flag_on_its_own_arms_the_config_reading_of_exit_1(sandbox, tmp_path, cfg):
    """Only `own_web_max` was exercised, so a mutation that stopped `--own` or `--own-from-origin`
    from arming the swallow survived: those two repos got the pre-016 behaviour and nothing said so."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)

    r = run(cfg, uvx_dir=_uvx_forcing_web_check_to(tmp_path, 1))

    assert r.returncode == 0, r.stdout + r.stderr
    assert "did NOT run" in (r.stdout + r.stderr)


def test_a_genuine_web_4_is_not_re_read_as_a_network_hiccup(sandbox, tmp_path):
    """web-check's codes are all in 0..4 and none of them means "unreachable", so its 4 — which is
    exactly how feature 016 reports an owned destination with no uuid — must survive the rc>3
    fail-open heuristic. Drop the RC_IS_FINAL immunity and this repo goes GREEN under the default."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)

    r = run({"mode": "max", "web": True, "own_web": ["owned"]},
            uvx_dir=_uvx_forcing_web_check_to(tmp_path, 4))

    assert r.returncode == 4, r.stdout + r.stderr


def test_after_a_fail_closed_config_error_the_later_axes_still_run(sandbox):
    """The 4 must be CARRIED, not bail()'d: bail exits the script and the create-readme / dangling
    axes never speak. Asserting only the exit code cannot tell the two apart — both give 4."""
    repo, run = sandbox
    (repo / "docs").mkdir()
    (repo / "docs" / "page.md").write_text("# page\n")
    (repo / "A.md").write_text("# A\nthe [docs](docs/)\ngone [g](nope/missing.md)\n")

    r = run({"mode": "max", "web": True, "own_web_max": 5, "fail_closed": True,
             "create_readme": True, "create_readme_excludes": ["mirrors/**"],
             "dangling": "repo"})
    out = r.stdout + r.stderr

    assert r.returncode == 4, out
    assert "create-readme axis" in out, out
    assert "dangling axis" in out, out


def test_a_single_empty_owner_is_named_not_swallowed(sandbox):
    """`["" ]` is the likeliest shape of the typo (a half-filled template line) and the one the
    joined value cannot distinguish from an absent key — it went through silently, axis running with
    no ownership at all and going green as if it had checked."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)

    r = run({"mode": "max", "web": True, "own_web": [""]})

    assert "every entry is empty" in (r.stdout + r.stderr), r.stdout + r.stderr


def test_some_empty_owners_among_good_ones_are_named_too(sandbox):
    """The all-empty case was covered and this one was not, so the config could list three owners,
    enforce one, and say nothing — fewer owners than the file claims, with a clean exit."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)

    r = run({"mode": "max", "web": True, "own_web": ["owned", "", ""]})

    assert "2 empty entry/entries out of" in (r.stdout + r.stderr), r.stdout + r.stderr


def test_own_web_of_only_empty_entries_still_trips_the_pass_never_runs_warning(sandbox):
    """F4 read presence off the JOINED value, so an owner list of empty strings looked absent to it
    too: configured under mode=check it said nothing at all."""
    repo, run = sandbox
    _owned_web_link_without_uuid(repo)

    r = run({"mode": "check", "web": True, "own_web": [""]})

    assert "NOT being applied" in (r.stdout + r.stderr), r.stdout + r.stderr


def test_a_bom_does_not_silently_turn_the_config_into_defaults(sandbox, tmp_path):
    """A config the gate CANNOT PARSE must not become a policy nobody wrote.

    `read_cfg` swallows any parse error into an empty dict, so before this test a UTF-8 BOM -- which
    `json` rejects and `jq` (and the PowerShell recipe) accept -- did not fail: it reverted EVERY key
    to its default. The gate then ran an old pinned version at mode=check with no excludes and
    reported a verdict about a file it had never read.

    Asserted on the INVOCATION, not the verdict: a silently-defaulted run is still green, which is
    precisely why this went unnoticed. Windows is the realistic source -- the repo ships a PowerShell
    recipe, and PowerShell writes a BOM by default.
    """
    repo, run = sandbox
    log = tmp_path / "argv.log"

    run({"mode": "check"}, argv_log=log)                       # baseline: what `check` looks like
    check_argv = log.read_text()
    log.unlink()

    # Same helper, then overwrite the file with the BOM'd bytes the helper cannot produce.
    run({"mode": "max"}, argv_log=log)
    cfg = repo / "darnlink-gate.json"
    cfg.write_bytes(b"\xef\xbb\xbf" + cfg.read_bytes())
    log.unlink()
    run_again = subprocess.run(["bash", str(RECIPE)], cwd=repo, env={**_clean_env(),
                               "DARNLINK_ARGV_LOG": str(log), "DARNLINK_BIN": _darnlink_bin(),
                               "PATH": f"{cfg.parent.parent / 'shimbin'}{os.pathsep}"
                                       + _clean_env().get("PATH", "")},
                               capture_output=True, text=True)
    assert log.exists(), run_again.stdout + run_again.stderr
    assert log.read_text() != check_argv, (
        "a BOM'd config reverted to the defaults instead of being honoured:\n" + log.read_text())


def test_a_bom_is_honoured_by_the_LENGTH_reader_too(sandbox, tmp_path):
    """The sibling reader, which the first BOM test did NOT gate.

    `read_cfg_len` is a second, separate python block, and mutating ONLY its encoding left the other
    test green -- a surviving mutant: a line that read as covered and was not.

    ⚠️ It cannot be asserted on the argv. `--own` reaches the CLI through `read_cfg` (which works),
    so the invocation is byte-identical whether or not `read_cfg_len` parsed. The only observable
    that depends on it is the WARNING it guards: `OWN_WEB_N` is the total the gate compares against
    the owners it actually used, so with `OWN_WEB_N = 0` the "some entries were empty" warning never
    fires -- and fewer owners get enforced than the config lists, silently, in green. Two mutants had
    to be hunted here to find an assertion that fails for the right reason.
    """
    repo, run = sandbox
    cfg = {"mode": "max", "web": True, "own_web": ["", "owned"]}   # 1 of 2 entries empty -> warns

    r = run(cfg)
    assert "empty entry/entries" in r.stderr, "el caso base ya no avisa: " + r.stderr

    run(cfg)                                                        # reescribe el config...
    f = repo / "darnlink-gate.json"
    f.write_bytes(b"\xef\xbb\xbf" + f.read_bytes())                # ...y se le antepone el BOM
    r2 = subprocess.run(["bash", str(RECIPE)], cwd=repo, capture_output=True, text=True,
                        env={**_clean_env(), "DARNLINK_BIN": _darnlink_bin(),
                             "PATH": f"{repo.parent / 'shimbin'}{os.pathsep}"
                                     + _clean_env().get("PATH", "")})
    assert "empty entry/entries" in r2.stderr, (
        "con BOM, read_cfg_len devolvio 0 y el aviso de owners vacios no salio:\n" + r2.stderr)
