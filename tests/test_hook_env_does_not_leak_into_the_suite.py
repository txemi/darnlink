"""`tools/check.sh` IS the pre-commit and pre-push hook, and a hook inherits git's environment.

Measured here, once: an ordinary `git commit` produced a commit that DELETED THE ENTIRE TREE, and
its message was `i` -- a string that appears nowhere in this project except a test fixture. Nothing
was wrong with the change being committed. git exports GIT_DIR to its hooks; the hook runs this
suite; four tests across two files legitimately build their own repo in a temp dir and shell out to
git; those child `git` calls were redirected at THIS repository, so a fixture's `git add -A` and
`git commit` landed on the real branch, mid-commit.

The working files survive -- the commit just stops describing them -- so the damage reads as a
catastrophic mistake by whoever committed, and `git status` afterwards calls the whole repo
untracked.

The same leak has a quieter second effect that is arguably worse: run by hand the suite is green,
run as the hook those same four tests fail. A gate that is red only when it is acting as the gate
teaches people to bypass it.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
CHECK_SH = Path(__file__).resolve().parent.parent / "tools" / "check.sh"
LEAKY = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_PREFIX")


def _guard_line() -> str:
    line = next((l for l in CHECK_SH.read_text(encoding="utf-8").splitlines()
                 if l.startswith("unset ") and "GIT_DIR" in l), None)
    assert line, "tools/check.sh no longer unsets git's per-invocation environment"
    return line


def _where_does_a_child_git_point(tmp_path: Path, env_extra: dict, prelude: str = "") -> str:
    """Build a repo in a temp dir and ask the child git which repo it is actually talking to."""
    target = tmp_path / "elsewhere"
    script = f'{prelude}\ngit init -q "{target}"\ngit -C "{target}" rev-parse --absolute-git-dir\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env={**os.environ, **env_extra})
    return r.stdout.strip()


@requires_git
def test_the_leak_is_REAL_hooks_redirect_a_child_git_at_this_repo(tmp_path):
    """The control. Without it the test below passes on a suite that was never vulnerable, and this
    file asserts nothing. My first attempt at this control FAILED -- I had guessed GIT_INDEX_FILE
    alone and could not reproduce the damage, so the fix was withheld until the variable was pinned.
    Keeping the control is what turned a plausible story into a measured one."""
    here = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=CHECK_SH.parent,
                          capture_output=True, text=True, check=True).stdout.strip()
    got = _where_does_a_child_git_point(tmp_path, {"GIT_DIR": here})
    assert got == here, (
        "expected GIT_DIR to hijack a child git; if this no longer holds, git changed its behaviour "
        "and the guard in tools/check.sh needs re-measuring rather than trusting")


@requires_git
def test_the_guard_in_check_sh_stops_it(tmp_path):
    """Treatment: the SAME hijack, behind the exact `unset` line check.sh ships."""
    here = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=CHECK_SH.parent,
                          capture_output=True, text=True, check=True).stdout.strip()
    got = _where_does_a_child_git_point(tmp_path, {"GIT_DIR": here}, prelude=_guard_line())
    assert got != here, "the guard did not stop the redirect"
    assert got.startswith(str(tmp_path)), f"child git landed somewhere unexpected: {got}"


@pytest.mark.parametrize("var", LEAKY)
def test_every_variable_git_exports_to_hooks_is_cleared(var):
    """Named individually so dropping one from the list is a failure with the variable's name on it,
    rather than a silently narrower guard."""
    assert var in _guard_line(), f"{var} is no longer cleared before the suite runs"


def test_the_guard_runs_before_anything_that_shells_out():
    """Order is the property. An `unset` after `uv run pytest` is decoration: by then the tests have
    already run against the inherited environment."""
    lines = CHECK_SH.read_text(encoding="utf-8").splitlines()
    code = [(i, l) for i, l in enumerate(lines) if not l.strip().startswith("#")]
    unset = min(i for i, l in code if l.startswith("unset ") and "GIT_DIR" in l)
    runs = [i for i, l in code if "uvx " in l or "uv run" in l or "python3 tools/" in l]
    assert runs, "check.sh no longer runs anything — this test is measuring the wrong file"
    assert unset < min(runs), (
        f"the guard is at line {unset+1}, after the first child process at line {min(runs)+1}")
