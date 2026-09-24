"""One scrubbed environment for every `git` a test spawns.

A git hook exports `GIT_DIR` (and, for pre-commit, `GIT_INDEX_FILE`), and a child `git` obeys them
over `-C` and over the path given to `git init`. `tools/check.sh` unsets them before running the
suite, and `test_hook_env_does_not_leak_into_the_suite.py` pins that guard — but the guard protects
ONE surface. `uv run pytest` straight from a shell that has those variables (a hook of ANOTHER
repository, `.github/workflows/ci.yml`) never passes through it, and then:

    GIT_DIR set, no GIT_WORK_TREE, cwd inside a worktree
    `git init <tmp>` -> writes `core.bare = true` into the SHARED clone's config

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
    """The names `tools/check.sh` unsets, read from the script itself."""
    texto = script.read_text(encoding="utf-8")
    m = re.search(r"^unset\s+((?:[A-Z_]+\s*\\?\s*)+)$", texto, re.M)
    return tuple(m.group(1).replace("\\", " ").split()) if m else ()


CHECK_SH = Path(__file__).resolve().parents[1] / "tools" / "check.sh"
FUGAS = tuple(dict.fromkeys(_del_guardia(CHECK_SH) + _EXTRA))
if not _del_guardia(CHECK_SH):      # el `unset` cambió de forma: no se adivina, se avisa
    raise RuntimeError(
        "tests/gitenv.py could not read the `unset` line of tools/check.sh. Do NOT fall back to a "
        "hand-written list: that is exactly the drift this reader exists to prevent. Fix the regex "
        "or the script, and keep the two in step.")

GIT_ENV = {k: v for k, v in os.environ.items() if k not in FUGAS}
