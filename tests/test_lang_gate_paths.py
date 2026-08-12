"""The two paths `lang_gate.py` resolves must describe the SAME project.

WHY THESE EXIST (2026-08-12). The tool needs a tree to scan and a baseline to compare it against.
Both used to be derived from `__file__`, so both were wrong in the same way -- and therefore
agreed, and the gate worked by accident of location. Fixing only the baseline made things strictly
worse: run against a project carrying 1242 legacy lines with the tool installed elsewhere, it read
the real baseline and compared it against a count taken from an unrelated tree (`0 < 1242`),
printed "OK -- and it went DOWN", exited 0 over untouched debt, and invited the user to run
`--update-baseline`, which would have written that 0 into a tracked file.

Nothing caught it: five local gates, every CI check and the tool's own lang-gate were green. There
were no tests at all on this logic; a three-line one would have caught it. So the test that matters
is not "does it still pass in this repo" -- the broken version passed that too -- it is "do the two
paths point at the same project when the tool lives somewhere else".
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "lang_gate.py")
EXTS = [".md", ".py"]


def _baseline(count: int, files: dict) -> str:
    return json.dumps({"count": count, "scanned_exts": EXTS, "files": files})


def _repo(tmp_path, spanish_lines: int, baseline_count: int | None):
    """A throwaway git repo with `spanish_lines` of legacy Spanish and its own baseline."""
    repo = tmp_path / "project"
    (repo / "src").mkdir(parents=True)
    body = "".join(f"# esto es una linea con comentario en castellano numero {i}\n"
                   for i in range(spanish_lines))
    (repo / "src" / "legacy.py").write_text(body or "x = 1\n", encoding="utf-8")
    (repo / "tools").mkdir()
    if baseline_count is not None:
        (repo / "tools" / "lang_gate_baseline.json").write_text(
            _baseline(baseline_count, {"src/legacy.py": baseline_count}), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _run(args, cwd, tool=TOOL, env=None):
    e = dict(os.environ)
    e.pop("LANG_GATE_BASELINE", None)
    e.update(env or {})
    p = subprocess.run([sys.executable, str(tool), *args], cwd=str(cwd),
                       capture_output=True, text=True, env=e)
    return p.returncode, p.stdout + p.stderr


def _installed_elsewhere(tmp_path):
    """A copy of the tool OUTSIDE any repo -- the venv / uvx / shared-bin case."""
    d = tmp_path / "elsewhere" / "bin"
    d.mkdir(parents=True)
    dst = d / "lang_gate.py"
    shutil.copy(TOOL, dst)
    return dst


def test_scans_the_repo_not_the_tools_neighbourhood(tmp_path):
    """The regression: tool outside, cwd inside a repo carrying real debt.

    The broken version scanned the tool's parent directory (empty), found 0, compared it against
    the repo's baseline of 5 and cheerfully reported that the debt had gone DOWN.
    """
    repo = _repo(tmp_path, spanish_lines=5, baseline_count=5)
    rc, out = _run(["--baseline"], cwd=repo, tool=_installed_elsewhere(tmp_path))
    assert "went DOWN" not in out, f"counted a tree that is not the repo: {out}"
    assert "unchanged vs the baseline" in out, out
    assert rc == 0, out


def test_growth_is_still_detected_when_installed_elsewhere(tmp_path):
    """And the ratchet must still BITE from outside -- green is not the point, correct is."""
    repo = _repo(tmp_path, spanish_lines=9, baseline_count=5)
    rc, out = _run(["--baseline"], cwd=repo, tool=_installed_elsewhere(tmp_path))
    assert rc == 1, out
    assert "GREW" in out, out


def test_update_baseline_writes_the_repos_own_count(tmp_path):
    """The data-loss case: `--update-baseline` must record a count measured on THIS repo."""
    repo = _repo(tmp_path, spanish_lines=3, baseline_count=5)
    rc, out = _run(["--update-baseline"], cwd=repo, tool=_installed_elsewhere(tmp_path))
    assert rc == 0, out
    written = json.loads((repo / "tools" / "lang_gate_baseline.json").read_text(encoding="utf-8"))
    assert written["count"] == 3, f"wrote {written['count']}, expected the repo's own 3"
    assert written["files"], "the per-file map was wiped"


def test_update_baseline_refuses_a_foreign_baseline(tmp_path):
    """Belt and braces: never write a count for tree A into a baseline living outside tree A."""
    repo = _repo(tmp_path, spanish_lines=3, baseline_count=5)
    foreign = tmp_path / "somewhere_else.json"
    foreign.write_text(_baseline(99, {}), encoding="utf-8")
    rc, out = _run(["--update-baseline"], cwd=repo, env={"LANG_GATE_BASELINE": str(foreign)})
    assert rc == 1, out
    assert "REFUSING" in out, out
    assert json.loads(foreign.read_text(encoding="utf-8"))["count"] == 99, "clobbered it anyway"


def test_subdirectory_resolves_like_the_root(tmp_path):
    """cwd inside the repo but not at its root must not change the verdict."""
    repo = _repo(tmp_path, spanish_lines=5, baseline_count=5)
    assert _run(["--baseline"], cwd=repo) == _run(["--baseline"], cwd=repo / "src")


def test_explicit_env_baseline_still_wins(tmp_path):
    """The escape hatch for odd layouts keeps working for READS."""
    repo = _repo(tmp_path, spanish_lines=5, baseline_count=None)
    elsewhere = tmp_path / "custom.json"
    elsewhere.write_text(_baseline(5, {"src/legacy.py": 5}), encoding="utf-8")
    rc, out = _run(["--baseline"], cwd=repo, env={"LANG_GATE_BASELINE": str(elsewhere)})
    assert rc == 0, out
    assert "unchanged" in out, out


def test_no_git_repo_falls_back_to_the_cwd_and_says_so(tmp_path):
    """Degrading is allowed; degrading in silence, or onto someone else's tree, is not.

    The fallback must be the directory the user ran the tool from, never the tool's own location:
    a shared-bin install would otherwise judge the tool's repo (or `$HOME`) and report OK about a
    project it never looked at.
    """
    plain = tmp_path / "plain"
    (plain / "src").mkdir(parents=True)
    (plain / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _, out = _run(["--baseline"], cwd=plain, tool=_installed_elsewhere(tmp_path))
    assert "falling back to the current directory" in out, out


def test_a_vendored_baseline_inside_the_tree_is_never_adopted(tmp_path):
    """The hole a first attempt at this fix opened, and the reason there is no `beside` fallback.

    A vendored copy or submodule (tool AND its baseline) lives inside the scanned tree, so any
    "is it inside root?" test says yes while it belongs to a different project. Measured before
    removing it: rc=0, "OK -- and it went DOWN (0 < 1242)", and --update-baseline then overwrote
    that tracked 1242 with 0.
    """
    host = tmp_path / "host"
    (host / "src").mkdir(parents=True)
    (host / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    vendored = host / "third_party" / "dep" / "tools"
    vendored.mkdir(parents=True)
    shutil.copy(TOOL, vendored / "lang_gate.py")
    (vendored / "lang_gate_baseline.json").write_text(_baseline(1242, {"z.py": 1242}),
                                                     encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=host, check=True)

    rc, out = _run(["--baseline"], cwd=host, tool=vendored / "lang_gate.py")
    assert "went DOWN" not in out, f"adopted a foreign baseline: {out}"
    assert rc == 1, out

    rc, out = _run(["--update-baseline"], cwd=host, tool=vendored / "lang_gate.py")
    kept = json.loads((vendored / "lang_gate_baseline.json").read_text(encoding="utf-8"))
    assert kept["count"] == 1242, f"clobbered a foreign tracked baseline: {kept}"


def test_a_baseline_outside_the_tree_is_announced_on_read(tmp_path):
    """The escape hatch may point anywhere -- but a two-project comparison is said out loud."""
    repo = _repo(tmp_path, spanish_lines=5, baseline_count=None)
    elsewhere = tmp_path / "custom.json"
    elsewhere.write_text(_baseline(5, {"src/legacy.py": 5}), encoding="utf-8")
    _, out = _run(["--baseline"], cwd=repo, env={"LANG_GATE_BASELINE": str(elsewhere)})
    assert "points outside the tree being scanned" in out, out
