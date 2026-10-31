"""The two gate recipes run the same gate: `recipes/darnlink-gate` (bash, the reference) and
`recipes/darnlink-gate.ps1`.

They used to diverge on the same `darnlink-gate.json`: with `"mode": "MAX"` bash ran check and the
.ps1 ran max; the .ps1 ignored `dangling`, `dangling_max`, `default_branch` and
`create_readme_excludes`, ran `create_readme` only under max, and ran with every default when the
file did not parse; and in both, a flag set to any unknown string (`"disabled"`) turned it ON.

One table, below: for each config, the exit code and the darnlink command lines the gate must run
(what follows `uvx --from <ref> darnlink`, without the `--help` pre-flight). Each recipe is run
against the table with the same uvx shim, in the same kind of sandbox:

- bash where the other recipe tests run it (POSIX, with bash, git and the darnlink script);
- PowerShell wherever `pwsh` or `powershell` is on PATH, and skipped otherwise. CI has it on the
  Windows legs and on ubuntu runners, so a .ps1 that drifts from the table fails there, even though
  a Linux machine without PowerShell only ever checks the bash half.

The table is the contract, not a recording: an entry that disagrees with bash is a bug in one of
the two, and the fix goes where the contract says.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import pytest

from gitenv import GIT_ENV

ROOT = Path(__file__).resolve().parent.parent
BASH_RECIPE = ROOT / "recipes" / "darnlink-gate"
PS1_RECIPE = ROOT / "recipes" / "darnlink-gate.ps1"
WINDOWS = os.name == "nt" or sys.platform.startswith("win")
U = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

# Anything that would carry an outer config into the recipe under test.
_GATE_ENV = (
    "DARNLINK_REF", "DARNLINK_GATE_MODE", "DARNLINK_GATE_SCOPE", "DARNLINK_GATE_FAIL_CLOSED",
    "DARNLINK_GATE_WEB", "DARNLINK_GATE_CREATE_README", "DARNLINK_GATE_TOKEN_FILE",
    "DARNLINK_GATE_DANGLING", "DARNLINK_GATE_DANGLING_MAX", "DARNLINK_GATE_DEFAULT_BRANCH",
    "DARNLINK_GATE_OWN_WEB_FROM_ORIGIN", "DARNLINK_GATE_OWN_WEB_MAX", "DARNLINK_GATE_INCLUDE_MERMAID",
    "DARNLINK_GATE_FORGEJO_TOKEN_FILE",
)


def _darnlink_bin() -> Optional[str]:
    found = shutil.which("darnlink")
    if found:
        return found
    for name in ("darnlink", "darnlink.exe"):
        cand = Path(sys.executable).parent / name
        if cand.exists():
            return str(cand)
    return None


def _powershell() -> Optional[str]:
    return shutil.which("pwsh") or shutil.which("powershell")


# --- the trees -------------------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   cwd=repo, env=GIT_ENV, check=True, capture_output=True, text=True)


def clean(repo: Path) -> None:
    (repo / "A.md").write_text("# A\nnothing to see\n", encoding="utf-8")


def dir_link(repo: Path) -> None:
    """A plain link to a folder that has no README: only the create-readme axis sees it."""
    (repo / "docs").mkdir()
    (repo / "docs" / "page.md").write_text(f"---\nuuid: {U}\n---\n# page\n", encoding="utf-8")
    (repo / "A.md").write_text("# A\nSee [the docs](docs/) for more.\n", encoding="utf-8")


def plain_link(repo: Path) -> None:
    """A plain link to a file with a uuid: a strict finding (3), clean under mode=repair."""
    (repo / "T.md").write_text(f"---\nuuid: {U}\n---\n# T\n", encoding="utf-8")
    (repo / "A.md").write_text("# A\nsee [t](T.md)\n", encoding="utf-8")


def dangling(repo: Path) -> None:
    """A link to a path that does not exist: only the dangling axis sees it."""
    (repo / "A.md").write_text("# A\nsee [gone](missing.md)\n", encoding="utf-8")


def dangling_staged(repo: Path) -> None:
    """The commit ADDS a dangling link: `added-lines` must stop it."""
    clean(repo)
    _git(repo, "add", "A.md")
    _git(repo, "commit", "-q", "-m", "base")
    (repo / "A.md").write_text("# A\nnothing to see\nsee [gone](missing.md)\n", encoding="utf-8")
    _git(repo, "add", "A.md")


def old_debt_staged(repo: Path) -> None:
    """The dangling link is OLD; the commit only adds a clean line: `added-lines` lets it through."""
    dangling(repo)
    _git(repo, "add", "A.md")
    _git(repo, "commit", "-q", "-m", "base")
    (repo / "A.md").write_text("# A\nsee [gone](missing.md)\nmore text\n", encoding="utf-8")
    _git(repo, "add", "A.md")


# --- the table ---------------------------------------------------------------------------------------

CHECK = "check ."
CHECK_JSON = "check . --json"
MAX = ". --robustify --create-frontmatter"
MAX_CR = ". --robustify --create-frontmatter --create-readme"
CR_PASS = ". --robustify --create-frontmatter --create-readme --json"
WEB = "web-check . --online"


@dataclass
class Case:
    id: str
    tree: Callable[[Path], None]
    config: object                     # dict -> json.dumps; bytes -> written as is
    rc: int
    argv: List[str]
    says: Optional[str] = None         # a substring of stdout+stderr
    env: dict = field(default_factory=dict)


def _flag(value, rc, argv, says=None):
    return Case(f"create_readme={value!r}", dir_link,
                {"ref": "x", "mode": "check", "create_readme": value}, rc, argv, says)


CASES = [
    # Row 44: a file that does not parse stops BOTH recipes, before anything runs.
    Case("invalid-json-trailing-comma", clean, b'{"mode": "max",}', 1, [], "not valid JSON"),
    Case("invalid-json-empty", clean, b"", 1, [], "not valid JSON"),
    Case("invalid-json-utf16", clean, '{"mode": "max"}'.encode("utf-16"), 1, [], "not valid JSON"),
    Case("bom-is-fine", clean, b'\xef\xbb\xbf{"ref": "x", "mode": "max"}', 0, [CHECK, MAX]),

    # Row 45: a flag is one of a CLOSED list; anything else stops the gate, naming key and value.
    _flag("disabled", 1, [], "create_readme='disabled'"),
    _flag("enabled", 1, [], "is not a boolean"),
    _flag("on ", 1, [], "is not a boolean"),           # bash does not trim, so neither does the .ps1
    _flag(0.0, 1, [], "create_readme='0.0'"),          # bash reads it "0.0", PowerShell would say "0"
    _flag(["x"], 1, [], "is not a boolean"),
    _flag("yes", 1, [CHECK, CR_PASS], "no README"),
    _flag("ON", 1, [CHECK, CR_PASS], "no README"),
    _flag(True, 1, [CHECK, CR_PASS], "no README"),
    _flag(1, 1, [CHECK, CR_PASS], "no README"),
    _flag("off", 0, [CHECK]),
    _flag("False", 0, [CHECK]),
    _flag(False, 0, [CHECK]),
    _flag(0, 0, [CHECK]),
    _flag("", 0, [CHECK]),
    _flag(None, 0, [CHECK]),
    _flag([], 0, [CHECK]),
    *[Case(f"{key}=disabled", clean, {"ref": "x", "mode": "max", key: "disabled"}, 1, [],
           f"{key}='disabled'")
      for key in ("fail_closed", "web", "own_web_from_origin", "include_mermaid", "create_readme")],
    Case("env-flag-disabled", clean, {"ref": "x"}, 1, [], "environment variable DARNLINK_GATE_FAIL_CLOSED",
         env={"DARNLINK_GATE_FAIL_CLOSED": "disabled"}),
    Case("env-flag-1", clean, {"ref": "x"}, 0, [CHECK], env={"DARNLINK_GATE_FAIL_CLOSED": "1"}),

    # Row 46: mode and scope are case-SENSITIVE (bash compares with `=`), keys too.
    Case("mode=max", clean, {"ref": "x", "mode": "max"}, 0, [CHECK, MAX]),
    Case("mode=MAX", clean, {"ref": "x", "mode": "MAX"}, 0, [CHECK]),
    Case("mode=Check", clean, {"ref": "x", "mode": "Check"}, 0, [CHECK]),
    Case("mode=true", clean, {"ref": "x", "mode": True}, 0, [CHECK]),
    Case("mode=repair", plain_link, {"ref": "x", "mode": "repair"}, 0, [CHECK]),
    Case("mode=Repair", plain_link, {"ref": "x", "mode": "Repair"}, 3, [CHECK]),
    Case("key-MODE", clean, {"ref": "x", "MODE": "max"}, 0, [CHECK]),
    Case("scope=staged", clean, {"ref": "x", "scope": "staged"}, 0, [], "no staged .md"),
    Case("scope=Staged", clean, {"ref": "x", "scope": "Staged"}, 0, [CHECK]),
    Case("scope=STAGED", clean, {"ref": "x", "scope": "STAGED"}, 0, [CHECK]),

    # Row 46: `dangling` and `dangling_max`, whole-repo and staged.
    Case("dangling-absent", dangling, {"ref": "x"}, 0, [CHECK]),
    Case("dangling=repo", dangling, {"ref": "x", "dangling": "repo"}, 1, [CHECK, CHECK_JSON], "[dangling]"),
    Case("dangling=REPO", dangling, {"ref": "x", "dangling": "REPO"}, 1, [CHECK, CHECK_JSON]),
    Case("dangling=true", dangling, {"ref": "x", "dangling": True}, 1, [CHECK, CHECK_JSON]),
    Case("dangling=warn", dangling, {"ref": "x", "dangling": "warn"}, 0, [CHECK, CHECK_JSON], "informational"),
    Case("dangling=added-lines-whole-repo", dangling, {"ref": "x", "dangling": "added-lines"}, 0,
         [CHECK, CHECK_JSON], "informational"),
    Case("dangling=sometimes", dangling, {"ref": "x", "dangling": "sometimes"}, 0, [CHECK], "unknown dangling"),
    Case("dangling_max=1", dangling, {"ref": "x", "dangling": "repo", "dangling_max": 1}, 0,
         [CHECK, CHECK_JSON], "exactly at the budget"),
    Case("dangling_max=2", dangling, {"ref": "x", "dangling": "repo", "dangling_max": 2}, 0,
         [CHECK, CHECK_JSON], "lower dangling_max"),
    Case("dangling_max=1.0", dangling, {"ref": "x", "dangling": "repo", "dangling_max": 1.0}, 1,
         [CHECK, CHECK_JSON], "not a non-negative integer"),
    Case("dangling_max=junk", dangling, {"ref": "x", "dangling": "repo", "dangling_max": "x"}, 1,
         [CHECK, CHECK_JSON], "not a non-negative integer"),
    Case("staged-added-lines-new", dangling_staged, {"ref": "x", "scope": "staged", "dangling": "added-lines"},
         1, [CHECK_JSON], "you are adding"),
    Case("staged-added-lines-old-debt", old_debt_staged,
         {"ref": "x", "scope": "staged", "dangling": "added-lines"}, 0, [CHECK_JSON], "clean"),
    Case("staged-warn", dangling_staged, {"ref": "x", "scope": "staged", "dangling": "warn"},
         0, [CHECK_JSON], "informational"),

    # Row 46: `create_readme` in any mode, and `create_readme_excludes` biting only its own pass.
    Case("create_readme-under-repair", dir_link, {"ref": "x", "mode": "repair", "create_readme": True},
         1, [CHECK, CR_PASS], "no README"),
    Case("create_readme-max-folded", dir_link, {"ref": "x", "mode": "max", "create_readme": True},
         1, [CHECK, MAX_CR]),
    Case("create_readme_excludes", dir_link,
         {"ref": "x", "mode": "check", "create_readme": True, "create_readme_excludes": ["docs"]},
         0, [CHECK, CR_PASS.replace(" --json", " --exclude docs --json")]),
    Case("create_readme_excludes-max", dir_link,
         {"ref": "x", "mode": "max", "create_readme": True, "create_readme_excludes": ["other"]},
         1, [CHECK, MAX, CR_PASS.replace(" --json", " --exclude other --json")], "no README"),
    # The web pass must fall through to the later axes (it used to `exit` in the .ps1).
    Case("web-then-create_readme", dir_link,
         {"ref": "x", "mode": "max", "web": True, "create_readme": True, "create_readme_excludes": ["other"]},
         1, [CHECK, MAX, WEB, CR_PASS.replace(" --json", " --exclude other --json")], "no README"),

    # The list keys reach every pass the same way.
    Case("excludes", dir_link, {"ref": "x", "mode": "check", "create_readme": True, "excludes": ["docs"]},
         0, ["check . --exclude docs", CR_PASS.replace(" --json", " --exclude docs --json")]),
    Case("ignore_blocks", clean, {"ref": "x", "ignore_blocks": ["gen"]}, 0, ["check . --ignore-block gen"]),

    # Row 46: `default_branch` reaches web-check; a JSON boolean is refused, a real name kept.
    Case("default_branch=main", clean, {"ref": "x", "mode": "max", "web": True, "default_branch": "main"},
         0, [CHECK, MAX, WEB + " --default-branch main"]),
    Case("default_branch=off", clean, {"ref": "x", "mode": "max", "web": True, "default_branch": "off"},
         0, [CHECK, MAX, WEB + " --default-branch off"]),
    Case("default_branch=true", clean, {"ref": "x", "mode": "max", "web": True, "default_branch": True},
         0, [CHECK, MAX, WEB], "looks like a JSON boolean"),
]


# --- the harness -----------------------------------------------------------------------------------

_SHIM = '''import subprocess, sys
args = sys.argv[1:]
if args[:1] == ["--from"]:
    args = args[2:]
if args[:1] == ["darnlink"]:
    args = args[1:]
with open({log!r}, "a", encoding="utf-8") as fh:
    fh.write(" ".join(args) + "\\n")
sys.exit(subprocess.call([{darnlink!r}, *args]))
'''


def _sandbox(tmp_path: Path, case: Case) -> tuple[Path, dict, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    case.tree(repo)
    cfg = repo / "darnlink-gate.json"
    if isinstance(case.config, bytes):
        cfg.write_bytes(case.config)
    else:
        cfg.write_text(json.dumps(case.config), encoding="utf-8")

    log = tmp_path / "argv.log"
    shim_dir = tmp_path / "shimbin"
    shim_dir.mkdir()
    shim = shim_dir / "shim.py"
    shim.write_text(_SHIM.format(log=str(log), darnlink=_darnlink_bin()), encoding="utf-8")
    if WINDOWS:
        (shim_dir / "uvx.cmd").write_text(
            f'@echo off\r\n"{sys.executable}" "{shim}" %*\r\nexit /b %ERRORLEVEL%\r\n', encoding="utf-8")
    else:
        uvx = shim_dir / "uvx"
        uvx.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{shim}" "$@"\n', encoding="utf-8")
        uvx.chmod(0o755)

    env = {k: v for k, v in GIT_ENV.items() if k not in _GATE_ENV}
    env["PATH"] = f"{shim_dir}{os.pathsep}" + env.get("PATH", "")
    env.update(case.env)
    return repo, env, log


def _observe(cmd: List[str], tmp_path: Path, case: Case) -> tuple[int, List[str], str]:
    repo, env, log = _sandbox(tmp_path, case)
    r = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=600)
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return r.returncode, [ln for ln in lines if ln != "--help"], r.stdout + r.stderr


def _check(case: Case, observed: tuple[int, List[str], str]) -> None:
    rc, argv, out = observed
    assert (rc, argv) == (case.rc, case.argv), f"{case.id}: got rc={rc} argv={argv}\n{out}"
    if case.says:
        assert case.says in out, f"{case.id}: {case.says!r} not in the output\n{out}"


@pytest.mark.skipif(WINDOWS or shutil.which("bash") is None or shutil.which("git") is None
                    or _darnlink_bin() is None,
                    reason="the bash half needs a POSIX bash, git and the darnlink script (as test_recipe_gate)")
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_bash_recipe_follows_the_table(case, tmp_path):
    _check(case, _observe(["bash", str(BASH_RECIPE)], tmp_path, case))


@pytest.mark.skipif(_powershell() is None or shutil.which("git") is None or _darnlink_bin() is None,
                    reason="no pwsh or powershell on PATH: the PowerShell half runs where CI has it")
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_powershell_recipe_follows_the_table(case, tmp_path):
    cmd = [_powershell(), "-NoProfile", "-NonInteractive"]
    if WINDOWS:
        cmd += ["-ExecutionPolicy", "Bypass"]
    _check(case, _observe(cmd + ["-File", str(PS1_RECIPE)], tmp_path, case))


def test_the_table_covers_every_key_the_recipes_read():
    """A key the table never sets is a key whose parity nobody checks."""
    from darnlink.gate_config import RECIPE_KEYS
    covered = set()
    for c in CASES:
        if isinstance(c.config, dict):
            covered |= set(c.config)
    # The owner/forge keys only act on a web destination, which needs the network to observe; their
    # wiring is tested in test_recipe_gate.py. `recipe_sha256` is read by whoever downloads the
    # recipe, not by it.
    elsewhere = {"own_web", "forgejo_web", "own_web_max", "recipe_sha256"}
    missing = set(RECIPE_KEYS) - elsewhere - covered
    assert not missing, sorted(missing)
