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

#: The variables that redirect a child `git` at the repository the hook is running for.
FUGAS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
         "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")

GIT_ENV = {k: v for k, v in os.environ.items() if k not in FUGAS}
