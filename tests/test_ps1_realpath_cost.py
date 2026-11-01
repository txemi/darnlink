"""MEASUREMENT ONLY, not meant to be merged: how much of the staged-scope PowerShell gate is spent in
`Resolve-RealPath` over findings that cannot match a staged file.

The gate resolves the path of EVERY finding (`Hits`), walking each component with `Get-Item`, to
compare it with the staged set. On a repo with many findings outside the commit that may be most of
the run. This test runs the recipe twice over the same tree, the real one and a copy whose
`Resolve-RealPathCore` returns `GetFullPath` (no walk), and reports both times as a warning, which
`pytest -q` prints in its summary. The difference is the most a pre-filter could save.
"""
from __future__ import annotations

import subprocess
import time
import warnings
from pathlib import Path

import pytest

from test_recipe_parity import (PS1_RECIPE, U, WINDOWS, Case, _darnlink_bin, _git, _powershell,
                                _sandbox)

N_FILES = 600
DEPTH = 6
ROUNDS = 3


def many_findings_one_clean_staged(repo: Path) -> None:
    (repo / "T.md").write_text(f"---\nuuid: {U}\n---\n# T\n", encoding="utf-8")
    for i in range(N_FILES):
        d = repo.joinpath(*[f"d{(i + k) % 4}" for k in range(DEPTH)])
        d.mkdir(parents=True, exist_ok=True)
        up = "../" * DEPTH
        (d / f"f{i}.md").write_text(f"# f{i}\nsee [t]({up}T.md) and [gone]({up}missing{i}.md)\n",
                                    encoding="utf-8")
    (repo / "A.md").write_text("# A\nnothing to see\n", encoding="utf-8")
    _git(repo, "add", "A.md")


CASE = Case("cost", many_findings_one_clean_staged, {"ref": "x", "scope": "staged", "dangling": "repo"},
            0, [])

NO_WALK = "function Resolve-RealPathCore([string]$path) {\n  return [IO.Path]::GetFullPath($path)\n"


def _time(cmd, repo, env) -> tuple[float, int, str]:
    best, rc, out = None, None, ""
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        r = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=1200, check=False)
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
        rc, out = r.returncode, r.stdout + r.stderr
    return best, rc, out


@pytest.mark.skipif(_powershell() is None or _darnlink_bin() is None, reason="needs PowerShell and darnlink")
def test_measure_realpath_cost(tmp_path):
    repo, env, _log = _sandbox(tmp_path, CASE)
    src = PS1_RECIPE.read_text(encoding="utf-8")
    head = "function Resolve-RealPathCore([string]$path) {\n"
    assert src.count(head) == 1
    no_walk = tmp_path / "no-walk.ps1"
    # Same encoding as the recipe (no BOM), so both copies are read the same way.
    no_walk.write_text(src.replace(head, NO_WALK), encoding="utf-8")
    base = [_powershell(), "-NoProfile", "-NonInteractive"] + (["-ExecutionPolicy", "Bypass"] if WINDOWS else [])
    t_real, rc_real, out_real = _time(base + ["-File", str(PS1_RECIPE)], repo, env)
    t_none, rc_none, out_none = _time(base + ["-File", str(no_walk)], repo, env)
    assert rc_real == 0, out_real
    assert rc_none == 0, out_none
    warnings.warn(f"REALPATH-COST windows={WINDOWS} files={N_FILES} depth={DEPTH} findings~{2 * N_FILES} "
                  f"real={t_real:.2f}s no_walk={t_none:.2f}s delta={t_real - t_none:.2f}s (best of {ROUNDS})")
