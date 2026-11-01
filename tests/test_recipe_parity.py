"""The two gate recipes run the same gate: `recipes/darnlink-gate` (bash, the reference) and
`recipes/darnlink-gate.ps1`.

They used to diverge on the same `darnlink-gate.json`: with `"mode": "MAX"` bash ran check and the
.ps1 ran max; the .ps1 ignored `dangling`, `dangling_max`, `default_branch` and
`create_readme_excludes`, ran `create_readme` only under max, and ran with every default when the
file did not parse; and in both, a flag set to any unknown string (`"disabled"`) turned it ON.

One table, below: for each config, the exit code and the darnlink command lines the gate must run
(what follows `uvx --from <ref> darnlink`, without the `--help` pre-flight and the `gate-config`
check that follows it). Each recipe is run against the table with the same uvx shim, in the same kind
of sandbox:

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


def symlink_staged(repo: Path) -> None:
    """The commit stages a SYMLINK to a file that carries a strict finding. darnlink reports the
    finding under the link's target, so the staged set only matches it once both sides are resolved
    (bash: `os.path.realpath`). Where a symlink cannot be created, the case is skipped."""
    plain_link(repo)
    (repo / "A.md").rename(repo / "real.md")
    _git(repo, "add", "T.md", "real.md")
    _git(repo, "commit", "-q", "-m", "base")
    try:
        os.symlink("real.md", repo / "link.md")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a symlink here: {exc}")
    _git(repo, "add", "link.md")


def clean_staged(repo: Path) -> None:
    clean(repo)
    _git(repo, "add", "A.md")


def accent_staged(repo: Path) -> None:
    """The commit stages a file whose NAME is not ASCII, with a strict finding in it. Without `-z`,
    `git diff --name-only` prints it quoted and escaped, and it matched no finding."""
    (repo / "T.md").write_text(f"---\nuuid: {U}\n---\n# T\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "canci\u00f3n.md").write_text("# C\nsee [t](../T.md)\n", encoding="utf-8")
    _git(repo, "add", "docs")


def broken_index_staged(repo: Path) -> None:
    """The index cannot be read, so `git diff --cached` fails (rc 128). That is not "nothing staged"."""
    clean(repo)
    (repo / ".git" / "index").write_bytes(b"this is not a git index\n" * 4)


def added_lines_unreadable_staged(repo: Path) -> None:
    """The staged LIST is readable but the added lines are not: the staged blob is gone from the object
    store, so `git diff --cached -U0` fails (rc 128) while `--name-only` (which compares ids) still
    works. The file's mtime is moved so git cannot read the working-tree copy instead."""
    dangling_staged(repo)
    oid = subprocess.run(["git", "rev-parse", ":A.md"], cwd=repo, env=GIT_ENV, check=True,
                         capture_output=True, text=True).stdout.strip()
    blob = repo / ".git" / "objects" / oid[:2] / oid[2:]
    blob.chmod(0o644)
    blob.unlink()
    st = (repo / "A.md").stat()
    os.utime(repo / "A.md", (st.st_atime, st.st_mtime + 10))


def accent_dangling_staged(repo: Path) -> None:
    """The commit ADDS a dangling link to a file whose NAME is not ASCII: `added-lines` must see it."""
    (repo / "docs").mkdir()
    (repo / "docs" / "canci\u00f3n.md").write_text("# C\nsee [gone](missing.md)\n", encoding="utf-8")
    _git(repo, "add", "docs")


def glob_name_old_debt_staged(repo: Path) -> None:
    """A staged file called `a*.md` carries OLD debt, and `ab.md` (staged too) adds lines at the same
    place. A pathspec read as a glob attributes the hunks of `ab.md` to `a*.md`, and the old dangling
    link looks new."""
    if WINDOWS:
        pytest.skip("a file name cannot contain `*` here")
    (repo / "a*.md").write_text("# A\nsee [gone](missing.md)\n", encoding="utf-8")
    (repo / "ab.md").write_text("# B\n", encoding="utf-8")
    _git(repo, "add", "a*.md", "ab.md")
    _git(repo, "commit", "-q", "-m", "base")
    (repo / "a*.md").write_text("# A\nsee [gone](missing.md)\nnew text\n", encoding="utf-8")
    (repo / "ab.md").write_text("# B\nx\ny\nz\n", encoding="utf-8")
    _git(repo, "add", "a*.md", "ab.md")


def hash_name_clean_staged(repo: Path) -> None:
    """A clean staged file whose name has a `#`. Pasted into a sed expression, the name broke it, and
    the gate died with rc 1 on a clean commit."""
    (repo / "C#notes.md").write_text("# C\nnothing to see\n", encoding="utf-8")
    _git(repo, "add", "C#notes.md")


def amp_name_dangling_staged(repo: Path) -> None:
    """A staged file whose name has a `&` ADDS a dangling link. Pasted into a sed replacement, `&` is
    "the match": the hunks went to `ab.md`, and the added link passed as old debt."""
    (repo / "a&b.md").write_text("# A\nsee [gone](missing.md)\n", encoding="utf-8")
    _git(repo, "add", "a&b.md")


def outside_a_repo_staged(repo: Path) -> None:
    """No git repository here at all (GIT_CEILING_DIRECTORIES stops git at the sandbox, so no parent one counts):
    `git diff --cached` exits 129 outside one, and that is not "nothing staged"."""
    (repo / "A.md").write_text("# A\nnothing to see\n", encoding="utf-8")
    (repo / ".git").rename(repo / "dot-git-moved-away")


# --- the table ---------------------------------------------------------------------------------------

CHECK = "check ."
CHECK_JSON = "check . --json"
MAX = ". --robustify --create-frontmatter"
MAX_CR = ". --robustify --create-frontmatter --create-readme"
CR_PASS = ". --robustify --create-frontmatter --create-readme --json"
WEB = "web-check . --online"
# Right after the `--help` pre-flight, both recipes ask whether the ref has `gate-config`, and run it.
GATE_CONFIG = ["gate-config --help", "gate-config darnlink-gate.json"]


@dataclass
class Case:
    id: str
    tree: Callable[[Path], None]
    config: object                     # dict -> json.dumps; bytes -> written as is
    rc: int
    argv: List[str]
    says: Optional[str] = None         # a substring of stdout+stderr
    env: dict = field(default_factory=dict)
    preflight: Optional[bool] = None   # does it get past the config into the pre-flight? (default: argv)
    gate_config: List[str] = field(default_factory=lambda: list(GATE_CONFIG))  # what follows `--help`
    args: List[str] = field(default_factory=list)  # passed to the recipe on its command line

    def head(self) -> List[str]:
        reached = bool(self.argv) if self.preflight is None else self.preflight
        return ["--help", *self.gate_config] if reached else []


def _flag(value, rc, argv, says=None):
    return Case(f"create_readme={value!r}", dir_link,
                {"ref": "x", "mode": "check", "create_readme": value}, rc, argv, says)


CASES = [
    # Row 44: a file that does not parse stops BOTH recipes, before anything runs.
    Case("invalid-json-trailing-comma", clean, b'{"mode": "max",}', 1, [], "not valid JSON"),
    Case("invalid-json-empty", clean, b"", 1, [], "not valid JSON"),
    Case("invalid-json-utf16", clean, '{"mode": "max"}'.encode("utf-16"), 1, [], "not valid JSON"),
    Case("bom-is-fine", clean, b'\xef\xbb\xbf{"ref": "x", "mode": "max"}', 0, [CHECK, MAX]),
    # Row 56: valid JSON whose top level is not an object stops both, as a file that does not parse.
    Case("root-array", clean, b'[1]', 1, [], "is not a JSON object"),
    Case("root-empty-array", clean, b' []', 1, [], "Its top level is an array"),
    Case("root-string", clean, b'"x"', 1, [], "Its top level is a string"),
    Case("root-number", clean, b'3', 1, [], "Its top level is a number"),
    Case("root-boolean", clean, b'true', 1, [], "Its top level is a boolean"),
    Case("root-null", clean, b'\nnull\n', 1, [], "Its top level is null"),

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
    Case("scope=staged", clean, {"ref": "x", "scope": "staged"}, 0, [], "no staged .md", preflight=True),
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
    # Row 53: a staged path that goes through a symlink matches the finding at the link's target.
    Case("staged-symlink", symlink_staged, {"ref": "x", "scope": "staged"}, 3, [CHECK_JSON], "un-anchored"),
    # Row 54: a staged name outside ASCII is read verbatim (`git diff -z`), not quoted.
    Case("staged-non-ascii-name", accent_staged, {"ref": "x", "scope": "staged"}, 3, [CHECK_JSON],
         "un-anchored"),

    # Row 55: exit 4 is "could not gate", and only under fail_closed: the pre-flight fails, a pass dies
    # above darnlink's own codes, or an optional axis cannot be evaluated. Fail-open skips with 0.
    Case("fail_closed-preflight-down", clean, {"ref": "x", "fail_closed": True}, 4, [],
         "fail-closed is on", env={"SHIM_FAIL": "--help", "SHIM_FAIL_RC": "2"},
         preflight=True, gate_config=[]),
    Case("fail-open-preflight-down", clean, {"ref": "x"}, 0, [], "SKIP",
         env={"SHIM_FAIL": "--help", "SHIM_FAIL_RC": "2"}, preflight=True, gate_config=[]),
    Case("fail_closed-check-dies", clean, {"ref": "x", "fail_closed": True}, 4, [CHECK],
         "fail-closed is on", env={"SHIM_FAIL": CHECK}),
    Case("fail_closed-env-check-dies", clean, {"ref": "x"}, 4, [CHECK], "fail-closed is on",
         env={"SHIM_FAIL": CHECK, "DARNLINK_GATE_FAIL_CLOSED": "1"}),
    Case("fail-open-check-dies", clean, {"ref": "x"}, 0, [CHECK], "SKIP", env={"SHIM_FAIL": CHECK}),
    Case("fail_closed-create_readme-down", dir_link, {"ref": "x", "create_readme": True, "fail_closed": True},
         4, [CHECK, CR_PASS], "fail-closed is on", env={"SHIM_FAIL": CR_PASS}),
    Case("fail_closed-dangling-down", dangling, {"ref": "x", "dangling": "repo", "fail_closed": True},
         4, [CHECK, CHECK_JSON], "fail-closed is on", env={"SHIM_FAIL": CHECK_JSON}),
    Case("fail_closed-staged-down", clean_staged, {"ref": "x", "scope": "staged", "fail_closed": True},
         4, [CHECK_JSON], "fail-closed is on", env={"SHIM_FAIL": CHECK_JSON}),
    # The staged list is how the gate looks at the commit: a git that fails to give it is "could not
    # look" (exit 4 under fail_closed, a skip otherwise), never an empty set that passes.
    Case("fail_closed-staged-list-git-fails", broken_index_staged,
         {"ref": "x", "scope": "staged", "fail_closed": True}, 4, [],
         "cannot list the staged files", preflight=True),
    Case("fail_closed-env-staged-list-git-fails", broken_index_staged, {"ref": "x", "scope": "staged"}, 4, [],
         "cannot list the staged files", env={"DARNLINK_GATE_FAIL_CLOSED": "1"}, preflight=True),
    Case("fail-open-staged-list-git-fails", broken_index_staged, {"ref": "x", "scope": "staged"}, 0, [],
         "cannot list the staged files", preflight=True),
    # The added lines of each staged file come from a second git call: one that fails is "could not
    # look" too, never an empty set under which every added dangling link passes.
    Case("fail_closed-added-lines-git-fails", added_lines_unreadable_staged,
         {"ref": "x", "scope": "staged", "dangling": "added-lines", "fail_closed": True}, 4, [CHECK_JSON],
         "cannot read the added lines of A.md"),
    Case("fail_closed-env-added-lines-git-fails", added_lines_unreadable_staged,
         {"ref": "x", "scope": "staged", "dangling": "added-lines"}, 4, [CHECK_JSON],
         "cannot read the added lines of A.md", env={"DARNLINK_GATE_FAIL_CLOSED": "1"}),
    Case("fail-open-added-lines-git-fails", added_lines_unreadable_staged,
         {"ref": "x", "scope": "staged", "dangling": "added-lines"}, 0, [CHECK_JSON],
         "cannot read the added lines of A.md"),
    Case("staged-added-lines-non-ascii-name", accent_dangling_staged,
         {"ref": "x", "scope": "staged", "dangling": "added-lines"}, 1, [CHECK_JSON], "[dangling]"),
    Case("staged-added-lines-glob-name", glob_name_old_debt_staged,
         {"ref": "x", "scope": "staged", "dangling": "added-lines"}, 0, [CHECK_JSON], "clean"),
    Case("staged-added-lines-hash-name", hash_name_clean_staged,
         {"ref": "x", "scope": "staged", "dangling": "added-lines"}, 0, [CHECK_JSON], "clean"),
    Case("staged-added-lines-amp-name", amp_name_dangling_staged,
         {"ref": "x", "scope": "staged", "dangling": "added-lines"}, 1, [CHECK_JSON], "[dangling]"),
    # Outside a git repository `git diff --cached` exits 129: "could not look", not "nothing staged".
    Case("fail_closed-staged-outside-a-repo", outside_a_repo_staged,
         {"ref": "x", "scope": "staged", "fail_closed": True}, 4, [],
         "cannot list the staged files", preflight=True),
    Case("fail-open-staged-outside-a-repo", outside_a_repo_staged, {"ref": "x", "scope": "staged"}, 0, [],
         "cannot list the staged files", preflight=True),
    # Row 55: `web` with scope=staged runs no web pass: the staged scope judges `check --json` only.
    Case("web-staged-clean", clean_staged, {"ref": "x", "mode": "max", "web": True, "scope": "staged"},
         0, [CHECK_JSON], "clean"),
    Case("web-staged-strict", accent_staged, {"ref": "x", "mode": "max", "web": True, "scope": "staged"},
         3, [CHECK_JSON], "un-anchored"),

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

    # Row 56: command-line arguments are not forwarded to darnlink (bash never did); --write is refused.
    # They are ignored, not an error (a pre-commit hook with `pass_filenames: true` passes file names),
    # and said once on stderr.
    Case("args-not-forwarded", clean, {"ref": "x"}, 0, [CHECK],
         "ignoring 2 command-line argument(s) (first: --exclude)", args=["--exclude", "A.md"]),
    Case("args-not-forwarded-max", clean, {"ref": "x", "mode": "max"}, 0, [CHECK, MAX],
         "ignoring 1 command-line argument(s) (first: --json)", args=["--json"]),
    Case("args-write-refused", clean, {"ref": "x"}, 1, [], "refusing --write", args=["--write"]),

    # Row 51: `gate-config` warns and never changes the verdict; a ref without it is said, not fatal.
    Case("gate-config-warns", clean, {"ref": "x", "mode": "check", "exclude": ["docs"]}, 0, [CHECK],
         "'exclude'"),
    Case("gate-config-old-ref", clean, {"ref": "x", "mode": "max"}, 0, [CHECK, MAX],
         "has no 'darnlink gate-config'", env={"SHIM_NO_GATE_CONFIG": "1"},
         gate_config=["gate-config --help"]),
    Case("gate-config-force-color", clean, {"ref": "x", "mode": "check", "exclude": ["docs"]}, 0, [CHECK],
         "'exclude'", env={"FORCE_COLOR": "1"}),
]


# --- the harness -----------------------------------------------------------------------------------

_SHIM = '''import os, subprocess, sys
args = sys.argv[1:]
if args[:1] == ["--from"]:
    args = args[2:]
if args[:1] == ["darnlink"]:
    args = args[1:]
with open({log!r}, "a", encoding="utf-8") as fh:
    fh.write(" ".join(args) + "\\n")
run = args
if os.environ.get("SHIM_NO_GATE_CONFIG") and args[:1] == ["gate-config"]:
    run = args[1:]  # a ref older than the subcommand: `gate-config --help` is the top-level help
# A darnlink that cannot run: the call whose argv starts with SHIM_FAIL exits SHIM_FAIL_RC, logged.
fail = os.environ.get("SHIM_FAIL")
if fail is not None and " ".join(args).startswith(fail):
    sys.exit(int(os.environ.get("SHIM_FAIL_RC", "127")))
sys.exit(subprocess.call([{darnlink!r}, *run]))
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
    # git never looks above the sandbox: a .git in a parent of the temp dir cannot leak into a row.
    env["GIT_CEILING_DIRECTORIES"] = str(repo.parent)
    env.update(case.env)
    return repo, env, log


def _observe(cmd: List[str], tmp_path: Path, case: Case) -> tuple[int, List[str], List[str], str]:
    repo, env, log = _sandbox(tmp_path, case)
    r = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=600)
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    probes = [ln for ln in lines if ln == "--help" or ln.startswith("gate-config")]
    argv = [ln for ln in lines if ln not in probes]
    # Every probe, and all of them before the first real pass: not one more, nor one further down.
    head = probes if lines[:len(probes)] == probes else ["out of place:", *lines]
    return r.returncode, head, argv, r.stdout + r.stderr


def _check(case: Case, observed: tuple[int, List[str], List[str], str]) -> None:
    rc, head, argv, out = observed
    assert (rc, head, argv) == (case.rc, case.head(), case.argv), \
        f"{case.id}: got rc={rc} head={head} argv={argv}\n{out}"
    if case.says:
        assert case.says in out, f"{case.id}: {case.says!r} not in the output\n{out}"


@pytest.mark.skipif(WINDOWS or shutil.which("bash") is None or shutil.which("git") is None
                    or _darnlink_bin() is None,
                    reason="the bash half needs a POSIX bash, git and the darnlink script (as test_recipe_gate)")
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_bash_recipe_follows_the_table(case, tmp_path):
    _check(case, _observe(["bash", str(BASH_RECIPE), *case.args], tmp_path, case))


@pytest.mark.skipif(_powershell() is None or shutil.which("git") is None or _darnlink_bin() is None,
                    reason="no pwsh or powershell on PATH: the PowerShell half runs where CI has it")
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_powershell_recipe_follows_the_table(case, tmp_path):
    cmd = [_powershell(), "-NoProfile", "-NonInteractive"]
    if WINDOWS:
        cmd += ["-ExecutionPolicy", "Bypass"]
    _check(case, _observe(cmd + ["-File", str(PS1_RECIPE), *case.args], tmp_path, case))


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
