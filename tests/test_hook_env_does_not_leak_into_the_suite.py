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

# ⚠️ The platform test comes FIRST and `shutil.which` is only a fallback: on a GitHub windows-latest
# runner `bash` IS on PATH -- it is the WSL launcher -- so `which` finds it and then every invocation
# exits 1 with "Windows Subsystem for Linux has no installed distributions", in UTF-16. A
# `which("bash") is None` guard alone does not skip; it turns the whole Windows matrix red. Measured
# on this very PR: these two tests failed on all four Windows jobs, in exactly that way, and the
# sibling file `test_recipe_examples.py` already carried this same guard for the same reason.
#
# Only the two EXECUTING tests are skipped. The text checks below stay live on Windows: they are the
# ones most likely to rot and they cost nothing to run anywhere, and skipping the module wholesale
# would leave the Windows matrix validating none of this.
requires_bash = pytest.mark.skipif(
    sys.platform.startswith("win") or os.name == "nt" or shutil.which("bash") is None
    or shutil.which("git") is None,
    reason="the guard is POSIX shell; on Windows agents `bash` is the WSL launcher",
)
CHECK_SH = Path(__file__).resolve().parent.parent / "tools" / "check.sh"
# ⚠️ THIS LIST MUST NAME EVERY VARIABLE THE GUARD CLEARS. It listed four of seven, and a review
# seeded the gap: shrinking the `unset` to just those four left this file GREEN. A test whose
# docstring promises "dropping one is a failure with the variable's name on it" while silently
# ignoring three of them is worse than no test, because it is quoted as coverage.
LEAKY = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_PREFIX", "GIT_COMMON_DIR",
         "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE", "GIT_CONFIG_PARAMETERS")


def _guard_line() -> str:
    """The whole `unset` statement, continuations included — it spans two lines now, and reading only
    the first would silently stop checking the variables on the second."""
    text = CHECK_SH.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("unset ") and "GIT_DIR" in l), None)
    assert start is not None, "tools/check.sh no longer unsets git's per-invocation environment"
    out = [lines[start]]
    while out[-1].rstrip().endswith("\\") and start + len(out) < len(lines):
        out.append(lines[start + len(out)])
    return " ".join(l.rstrip("\\").strip() for l in out)


def _where_does_a_child_git_point(tmp_path: Path, env_extra: dict, prelude: str = "") -> str:
    """Build a repo in a temp dir and ask the child git which repo it is actually talking to."""
    target = tmp_path / "elsewhere"
    script = f'{prelude}\ngit init -q "{target}"\ngit -C "{target}" rev-parse --absolute-git-dir\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env={**os.environ, **env_extra})
    return r.stdout.strip()


@requires_bash
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


@requires_bash
def test_the_guard_in_check_sh_stops_it(tmp_path):
    """Treatment: the SAME hijack, behind the exact `unset` line check.sh ships."""
    here = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=CHECK_SH.parent,
                          capture_output=True, text=True, check=True).stdout.strip()
    got = _where_does_a_child_git_point(tmp_path, {"GIT_DIR": here}, prelude=_guard_line())
    assert got != here, "the guard did not stop the redirect"
    assert got.startswith(str(tmp_path)), f"child git landed somewhere unexpected: {got}"


@pytest.mark.parametrize("var", LEAKY)
def test_every_variable_the_guard_CLEARS_is_named_here(var):
    """Named individually so dropping one from the guard is a failure with the variable's name on it,
    rather than a silently narrower guard.

    ⚠️ The name says "the guard clears", not "git exports", and the difference is deliberate. git also
    exports GIT_AUTHOR_NAME/EMAIL/DATE, GIT_EDITOR and GIT_EXEC_PATH to hooks, and those are left
    alone on purpose: the author/editor set only affects commits a test makes in its OWN repo, which
    is harmless, and clearing GIT_EXEC_PATH could break git itself on an unusual install. The list
    here is the contract of the guard, and an earlier name overclaimed it as the contract of git."""
    assert var in _guard_line(), f"{var} is no longer cleared before the suite runs"


def test_the_guard_runs_before_anything_that_shells_out():
    """Order is the property. An `unset` after `uv run pytest` is decoration: by then the tests have
    already run against the inherited environment."""
    lines = CHECK_SH.read_text(encoding="utf-8").splitlines()
    code = [(i, l) for i, l in enumerate(lines) if not l.strip().startswith("#")]
    unset = min(i for i, l in code if l.startswith("unset ") and "GIT_DIR" in l)  # noqa: A001
    runs = [i for i, l in code if "uvx " in l or "uv run" in l or "python3 tools/" in l]
    assert runs, "check.sh no longer runs anything — this test is measuring the wrong file"
    assert unset < min(runs), (
        f"the guard is at line {unset+1}, after the first child process at line {min(runs)+1}")
