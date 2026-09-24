"""Every `git` the suite spawns must carry a scrubbed environment — checked, not remembered.

`tools/check.sh` unsets `GIT_DIR` and friends before running the tests, and
`test_hook_env_does_not_leak_into_the_suite.py` pins that guard. But the guard protects ONE
surface: `uv run pytest` from a shell that has those variables — a hook of ANOTHER repository, or
`.github/workflows/ci.yml` — never passes through it. And then a `git init` inside a worktree
writes `core.bare = true` into the SHARED clone's config, which leaves every worktree of that clone
unusable. Measured on throwaway repositories: `false` before the call, `true` after.

So this file is the cheap half of the defence: it reads the suite and fails if any `git` call site
forgot `env=`. A rule nobody measures is a rule that comes back on the next test someone writes.
"""
from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent

#: Its whole point is to run git WITH the leaked variables, to prove the leak is real. Cleaning it
#: would leave the control asserting nothing.
EXENTOS = {"test_hook_env_does_not_leak_into_the_suite.py"}


def _llamadas_sin_env(fuente: str) -> list[int]:
    arbol = ast.parse(fuente)
    fuera = []
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Call) and getattr(nodo.func, "attr", "") in ("run", "Popen")):
            continue
        trozo = ast.get_source_segment(fuente, nodo) or ""
        if ('"git"' in trozo or "'git'" in trozo or '["git' in trozo) and "env=" not in trozo:
            fuera.append(nodo.lineno)
    return fuera


def test_no_git_call_in_the_suite_runs_with_the_inherited_environment():
    culpables = {}
    for p in sorted(TESTS.glob("test_*.py")):
        if p.name in EXENTOS:
            continue
        lineas = _llamadas_sin_env(p.read_text(encoding="utf-8"))
        if lineas:
            culpables[p.name] = lineas
    assert not culpables, (
        "these git calls inherit the environment, so under a hook (or any shell with GIT_DIR set) "
        "they act on the REAL repository: " + str(culpables) +
        ". Pass env=GIT_ENV (tests/gitenv.py).")


def test_the_check_itself_would_catch_a_new_offender():
    """The control: a clean file passes and a dirty one fails. Without it, a broken parser would
    report «nothing to fix» for ever — the failure mode this project keeps measuring."""
    sucio = 'import subprocess\nsubprocess.run(["git", "init", "-q", "x"], check=True)\n'
    limpio = 'import subprocess\nsubprocess.run(["git", "init", "-q", "x"], check=True, env={})\n'
    assert _llamadas_sin_env(sucio) == [2]
    assert _llamadas_sin_env(limpio) == []


def test_the_list_covers_everything_the_real_guard_unsets():
    """The blocker this file was sent back for: the list used to be hand-written and covered LESS
    than `tools/check.sh` — it lacked `GIT_NAMESPACE` and `GIT_CONFIG_PARAMETERS`, and the second
    one carries the invoking git's `-c` options (`core.hooksPath` among them), so a child
    `git commit` in a temp repo could re-enter THIS repository's hooks. It is now read from the
    script; this pins that it stays a superset even if someone reverts to a literal."""
    import gitenv

    guarda = set(gitenv._del_guardia(gitenv.CHECK_SH))
    assert guarda, "the `unset` line of tools/check.sh could not be read"
    assert {"GIT_DIR", "GIT_NAMESPACE", "GIT_CONFIG_PARAMETERS"} <= guarda, guarda
    assert guarda <= set(gitenv.FUGAS), sorted(guarda - set(gitenv.FUGAS))
