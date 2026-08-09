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
    "DARNLINK_GATE_DANGLING",
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
        'exec "${DARNLINK_BIN:-darnlink}" "${args[@]}"\n'
    )
    shim.chmod(0o755)

    def run(config: dict) -> subprocess.CompletedProcess:
        (repo / "darnlink-gate.json").write_text(json.dumps(config))
        env = _clean_env()
        env["PATH"] = f"{bindir}{os.pathsep}" + env.get("PATH", "")
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
    dbin = _darnlink_bin()

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([needed["git"], "init", "-q"], cwd=repo, check=True)
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

    env = {k: v for k, v in os.environ.items() if k not in _LEAKY_ENV}
    env["PATH"] = str(bindir)  # only the minimal bin → python3 is unreachable
    env["DARNLINK_BIN"] = dbin
    env["DARNLINK_GATE_MODE"] = "check"
    env["DARNLINK_GATE_CREATE_README"] = "1"  # request the axis via env (no python3 to read the json)
    # sanity: python3 really is unreachable through this PATH
    assert subprocess.run([needed["bash"], "-c", "command -v python3"], env=env,
                          capture_output=True).returncode != 0

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
