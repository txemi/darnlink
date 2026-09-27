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


#: The process launchers worth looking at. `run`/`Popen` are not the only ones: review seeded
#: `subprocess.call`, `check_call`, `check_output`, `from subprocess import run` (where `func` is an
#: `ast.Name`, not an attribute) and `os.system`, and all five slipped through.
_LANZADORES = ("run", "Popen", "call", "check_call", "check_output")


def _alias(arbol: ast.AST) -> tuple[set, set, set]:
    """What `subprocess` and `os` are called here, and what was imported FROM subprocess.

    Without this the rule flagged any `run(something)`: this suite has local helpers named `run`
    (test_privacy_gate, test_recipe_gate) and they came out as 13 false culprits. A ratchet that
    shouts where there is nothing gets switched off, so scoping it is part of the fix."""
    sp, oss, desde_sp = set(), set(), set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            for a in n.names:
                (sp if a.name == "subprocess" else oss if a.name == "os" else set()).add(a.asname or a.name)
        elif isinstance(n, ast.ImportFrom) and n.module in ("subprocess", "os"):
            for a in n.names:
                desde_sp.add(a.asname or a.name)
    return sp, oss, desde_sp


def _nombre_del_lanzador(nodo: ast.Call, sp: set, oss: set, desde_sp: set) -> str:
    """The launcher's name IF the call resolves to subprocess/os; otherwise an empty string."""
    f = nodo.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        if f.value.id in sp or f.value.id in oss:
            return f.attr
        return ""
    if isinstance(f, ast.Name) and f.id in desde_sp:
        return f.id
    return ""


def _menciona_git(nodo: ast.Call) -> bool:
    """A literal `git` as the list's first element, or at the start of the string."""
    if not nodo.args:
        return False
    a = nodo.args[0]
    if isinstance(a, ast.List) and a.elts and isinstance(a.elts[0], ast.Constant):
        return str(a.elts[0].value) == "git"
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        return a.value == "git" or a.value.startswith("git ")
    return False


def _llamadas_sin_env(fuente: str) -> list[int]:
    arbol = ast.parse(fuente)
    sp, oss, desde_sp = _alias(arbol)
    fuera = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        nombre = _nombre_del_lanzador(nodo, sp, oss, desde_sp)
        if nombre == "system":                       # os.system takes no env: there is no clean way out
            if _menciona_git(nodo):
                fuera.append(nodo.lineno)
            continue
        if nombre not in _LANZADORES:
            continue
        # `env=` MUST be an argument of THIS call. Matching it as a substring of the source read a
        # nested one as clean: `run(["git",…], cwd=helper(), text="env=fake")` passed.
        if any(k.arg == "env" for k in nodo.keywords):
            continue
        if _menciona_git(nodo):
            fuera.append(nodo.lineno)
        elif nodo.args and isinstance(nodo.args[0], ast.Name):
            # A command held in a variable cannot be read from here: unverifiable is not the same
            # as clean. The way out is to pass `env=` or write the list inline.
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
        "they act on the REAL repository, or hold the command in a variable and cannot be "
        "checked from here: " + str(culpables) +
        ". Pass env=GIT_ENV (tests/gitenv.py), or write the command inline.")


def test_the_check_itself_would_catch_a_new_offender():
    """The control: a clean file passes and a dirty one fails. Without it, a broken parser would
    report «nothing to fix» for ever — the failure mode this project keeps measuring."""
    sucio = 'import subprocess\nsubprocess.run(["git", "init", "-q", "x"], check=True)\n'
    limpio = 'import subprocess\nsubprocess.run(["git", "init", "-q", "x"], check=True, env={})\n'
    assert _llamadas_sin_env(sucio) == [2]
    assert _llamadas_sin_env(limpio) == []
    # The blind spot review measured: the command in a variable is now flagged, not passed over.
    variable = 'import subprocess\ncmd = ["git", "status"]\nsubprocess.run(cmd)\n'
    variable_ok = 'import subprocess\ncmd = ["git", "status"]\nsubprocess.run(cmd, env={})\n'
    assert _llamadas_sin_env(variable) == [3]
    assert _llamadas_sin_env(variable_ok) == []
    # The four shapes review seeded that used to pass, plus the nested `env=`.
    otras = {
        'import subprocess\nsubprocess.check_output(["git", "log"])\n': [2],
        'import subprocess\nsubprocess.call(["git", "log"])\n': [2],
        'from subprocess import run\nrun(["git", "log"])\n': [2],
        'import os\nos.system("git init x")\n': [2],
        'import subprocess\nsubprocess.run(["git","status"], text="env=falso")\n': [2],
        'import subprocess as sp\nsp.run(["git", "log"])\n': [2],
        # And what it must NOT flag: a local helper that happens to be called `run`.
        'def run(cfg):\n    return cfg\nrun({"a": 1})\n': [],
    }
    for fuente, esperado in otras.items():
        assert _llamadas_sin_env(fuente) == esperado, fuente


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
