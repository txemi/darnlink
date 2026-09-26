"""One scrubbed environment for every `git` a test spawns.

A git hook exports `GIT_DIR` (and, for pre-commit, `GIT_INDEX_FILE`), and a child `git` obeys them
over `-C` and over the path given to `git init`. `tools/check.sh` unsets them before running the
suite, and `test_hook_env_does_not_leak_into_the_suite.py` pins that guard — but the guard protects
ONE surface. `uv run pytest` straight from a shell that has those variables (a hook of ANOTHER
repository, `.github/workflows/ci.yml`) never passes through it, and then:

    GIT_DIR = the WORKTREE's git-dir (<clone>/.git/worktrees/<name>, which is exactly what a hook
    running there exports), no GIT_WORK_TREE
    `git init <tmp>` -> writes `core.bare = true` into the SHARED clone's config

The git-dir has to be the WORKTREE's, and that is the half a reviewer's first attempt missed: with
GIT_DIR pointing at the main `<clone>/.git` nothing happens. The mechanism explains why the damage
lands on the clone and not on the temp directory: with GIT_DIR set, `git init <path>` IGNORES the
path and REINITIALISES the git-dir ("Reinitialized existing Git repository in …/worktrees/wt/").

which leaves every worktree of that clone unusable ("this operation must be run in a work tree").
Measured on throwaway repositories: `false` before, `true` after. Cleaning the environment at each
call site is what survives someone entering by a door the guard does not cover.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

#: The variables that redirect a child `git` at the repository the hook is running for. The list is
#: NOT hand-kept: it is READ from the `unset` line of `tools/check.sh`, which is the guard that has
#: already been through a review of a real hook's dumped environment — so the two cannot drift, and
#: the drift is what review caught here (this copy was missing `GIT_NAMESPACE` and, worse,
#: `GIT_CONFIG_PARAMETERS`, which carries the invoking git's `-c` options: `core.hooksPath` among
#: them, so a child `git commit` in a temp repo could re-enter THIS repository's hooks).
#: `GIT_ALTERNATE_OBJECT_DIRECTORIES` is added on top: it is not in the guard, and an inherited one
#: makes a temp repo read objects from another.
_EXTRA = ("GIT_ALTERNATE_OBJECT_DIRECTORIES",)


def _del_guardia(script: Path) -> tuple:
    """The names `tools/check.sh` unsets, read from the script itself.

    It takes the `unset` statement that MENTIONS `GIT_DIR`, not the first one in the file, and it
    follows backslash continuations. Review seeded both ways of fooling a first-match reader: an
    unrelated `unset LC_ALL` earlier in the script made the list come out as `('LC_ALL',)` — not
    empty, so the RuntimeError below never fired and nothing was scrubbed; and splitting the git
    names across two `unset` statements silently dropped the second, which is exactly how the
    hand-kept list drifted the first time."""
    lineas = script.read_text(encoding="utf-8").splitlines()
    i = next((n for n, l in enumerate(lineas)
              if l.startswith("unset ") and "GIT_DIR" in l), None)
    if i is None:
        return ()
    bloque = [lineas[i]]
    while bloque[-1].rstrip().endswith("\\") and i + len(bloque) < len(lineas):
        bloque.append(lineas[i + len(bloque)])
    nombres = " ".join(l.rstrip("\\").strip() for l in bloque).removeprefix("unset ").split()
    # A git scrub that does not name GIT_DIR does not exist: if the block read lacks it, something
    # else was read, and no list is better than a short one.
    return tuple(nombres) if "GIT_DIR" in nombres else ()


CHECK_SH = Path(__file__).resolve().parents[1] / "tools" / "check.sh"
_GUARDIA = _del_guardia(CHECK_SH)
FUGAS = tuple(dict.fromkeys(_GUARDIA + _EXTRA))
if not _GUARDIA:                    # el `unset` cambió de forma: no se adivina, se avisa
    raise RuntimeError(
        "tests/gitenv.py could not read the `unset` line of tools/check.sh. Do NOT fall back to a "
        "hand-written list: that is exactly the drift this reader exists to prevent. Fix the regex "
        "or the script, and keep the two in step.")

GIT_ENV = {k: v for k, v in os.environ.items() if k not in FUGAS}
