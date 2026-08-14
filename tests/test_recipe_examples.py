"""The shipped CI examples are code, and until now nothing parsed or ran them.

This release's own *Fixed* entry is "nothing had ever parsed `recipes/darnlink-gate.ps1`" — and the
same commit put non-trivial shell into two example files with no gate at all. These are whole working
files people copy verbatim into a repo, so a syntax error or a wrong pin in them ships straight to an
adopter, and the adopter has no reason to doubt it.

The pin derivation gets the most attention because it is the piece that decides WHICH gate runs. A
derivation that quietly resolves to the wrong version is worse than a stale literal: the literal at
least tells you what it is.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Only the tests that EXECUTE the derivation need a POSIX shell. The text checks — no literal pin, the
# two examples agreeing, the YAML wiring, the lazy version — are the ones most likely to rot and cost
# nothing to run anywhere, so they stay live on Windows rather than being skipped with the rest. A
# module-wide skip here would have been the easy call and would have left the Windows matrix
# validating none of this.
#
# ⚠️ The platform test comes FIRST and `shutil.which` is only a fallback, because on a GitHub
# windows-latest runner `bash` IS on PATH: it is the WSL launcher, so `which` finds it and then every
# invocation exits 1 with "Windows Subsystem for Linux has no installed distributions" — a UTF-16
# message, which is how it arrived here. A `which("bash") is None` guard alone does not skip; it turns
# the whole matrix red. Measured on this very PR.
requires_bash = pytest.mark.skipif(
    sys.platform.startswith("win") or os.name == "nt" or shutil.which("bash") is None,
    reason="the derivation is POSIX shell; Windows agents run the .ps1 recipe instead",
)

EXAMPLES = Path(__file__).resolve().parent.parent / "recipes" / "examples"
ACTIONS = EXAMPLES / "github-actions-darnlink-gate.yml"
JENKINS = EXAMPLES / "Jenkinsfile-stage.groovy"
# Both examples are EXECUTED, not just compared. Running only the Actions one left the Jenkins file
# effectively ungated: an adversarial round sowed seven defects in it — a deleted failure guard, a
# silent `VER=v0.7.0` fallback, a `\.` that is a Groovy compile error, a curl repointed at another
# owner — and the suite stayed green on all seven, while the commit message claimed the mutations
# were killed. They were killed in the file the tests actually touched.
EXECUTED = (ACTIONS, JENKINS)

# Two extractions, on purpose. The python3 call is IDENTICAL in both examples and is compared as
# such; the failure branch is not — Actions wants a `::error::` annotation, Jenkins plain stderr.
# Both are extracted rather than duplicated here: a copy in the test would let the examples drift
# while the test kept passing against its own private copy.
_PY_RE = re.compile(r"(python3 -c '[^']*')")
_FULL_RE = re.compile(r"^[ \t]*(VER=\$\(python3 -c '[^']*'\)[ \t]*\\\n.*?\})", re.MULTILINE | re.DOTALL)


def _py_call(path: Path) -> str:
    m = _PY_RE.search(path.read_text(encoding="utf-8"))
    assert m, f"no `python3 -c …` derivation found in {path.name}"
    return m.group(1)


def _derivation(path: Path) -> str:
    """The WHOLE statement, guard included. Capturing only the assignment would be a test that cannot
    fail: `VER=$(false)` does not stop a script — the exit status belongs to whatever runs next — so
    the `|| { …; exit 1; }` branch IS the loudness, and a test that drops it proves nothing."""
    m = _FULL_RE.search(path.read_text(encoding="utf-8"))
    assert m, f"no guarded `VER=$(python3 -c …) || {{ … }}` statement found in {path.name}"
    return m.group(1)


def _run_derivation(cmd: str, cwd: Path):
    return subprocess.run(["bash", "-c", f"{cmd}\nprintf '%s' \"$VER\""],
                          cwd=cwd, capture_output=True, text=True)


def _cfg(tmp_path: Path, payload) -> Path:
    d = tmp_path / "repo"
    d.mkdir(exist_ok=True)
    (d / "darnlink-gate.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return d


def test_the_two_examples_derive_the_pin_identically():
    """They diverged once already: two hand-escaped regexes doing the same job, one of which was a
    Groovy compile error away from shipping broken. Identical text is the only cheap guarantee."""
    assert _py_call(ACTIONS) == _py_call(JENKINS)


@pytest.mark.parametrize("path", [
    ACTIONS, JENKINS,
    EXAMPLES / "README.md",
    # The canonical recipe README too, and it is the one that proves the point: the first pass fixed
    # its `curl` and left two config blocks pinned at v0.7.0 and v0.18.0 — so "there is only one pin"
    # was documented one directory down while the page people actually copy still shipped a rotten
    # one. A check that covers only the files you remembered is a check that finds what you already
    # knew. Concrete tags are placeholders here (`vX.Y.Z`), resolved on paste.
    EXAMPLES.parent / "README.md",
], ids=lambda p: p.name)
def test_no_shipped_recipe_doc_carries_a_literal_pin(path):
    """The failure this whole approach exists to prevent: a second copy of the version number.
    Measured on the day it was replaced — one file was 3 releases stale, the other 23 — and nothing
    had ever checked, which is exactly why both drifted."""
    literal = re.findall(r"darnlink[/@]v\d+\.\d+\.\d+", path.read_text(encoding="utf-8"))
    assert not literal, f"{path.name} reintroduced a literal pin: {literal}"


def test_the_actions_example_is_valid_yaml_and_wires_the_derivation_through():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(ACTIONS.read_text(encoding="utf-8"))
    steps = doc["jobs"]["gate"]["steps"]
    derive = next(s for s in steps if "python3 -c" in s.get("run", ""))
    fetch = next(s for s in steps if "curl" in s.get("run", ""))
    # Derived into GITHUB_ENV, and consumed by the fetch — a value written and never read is the
    # shape this would most plausibly break in, and it looks fine on inspection.
    assert "GITHUB_ENV" in derive["run"]
    assert "${DARNLINK_GATE_VERSION}" in fetch["run"]
    assert steps.index(derive) < steps.index(fetch)


def test_the_jenkins_example_fetches_the_version_it_derived():
    """The Actions example had this check and Jenkins did not, so the Jenkins file could derive
    `$VER` correctly and then fetch a hard-coded tag with the whole suite green — the exact failure
    this PR exists to prevent, surviving in the file it claimed to have covered. Measured: pointing
    its curl at a fixed tag left every test passing.

    Asserted on the fetch line rather than by parsing Groovy: what matters is that the URL consumes
    the derived value and nothing else, and no-literal-pin (above) is what stops it being replaced
    by a tag."""
    text = JENKINS.read_text(encoding="utf-8")
    fetch = next((l for l in text.splitlines() if "raw.githubusercontent.com" in l), None)
    assert fetch, "no curl of the recipe found in the Jenkins example"
    assert "$VER" in fetch, f"the fetch does not consume the derived version: {fetch.strip()}"
    assert "-f" in fetch, "curl must fail on a 404 rather than write '404: Not Found' to disk"
    assert text.index("VER=$(") < text.index("raw.githubusercontent.com"), "derive before fetch"


@pytest.mark.parametrize("path", [ACTIONS, JENKINS, EXAMPLES.parent / "README.md"],
                         ids=lambda p: p.name)
def test_every_recipe_fetch_points_at_this_repo(path):
    """These files are copy-paste templates that download a script and run it. Repointing the host
    or the owner is the highest-consequence single-token edit in the repo and nothing checked it:
    swapping `txemi/darnlink` for another owner left the whole suite green, in both examples and in
    the canonical README."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if "raw.githubusercontent.com" not in line:
            continue
        assert "raw.githubusercontent.com/txemi/darnlink/" in line, (
            f"{path.name} fetches the recipe from somewhere else: {line.strip()}")


@pytest.mark.parametrize("ref,expected", [
    ("git+https://github.com/txemi/darnlink@v0.22.0", "v0.22.0"),
    ("git+https://github.com/txemi/darnlink@main", "main"),          # a branch the recipe accepts
    ("git+https://github.com/txemi/darnlink@aa529ac", "aa529ac"),    # and a SHA
    ("git+ssh://git@github.com/txemi/darnlink@v0.22.0", "v0.22.0"),  # an @ in the HOST must not win
])
@pytest.mark.parametrize("example", EXECUTED, ids=lambda p: p.name)
@requires_bash
def test_every_ref_shape_the_recipe_accepts_survives_the_derivation(tmp_path, example, ref, expected):
    """The first draft matched only `vX.Y.Z`, which hard-failed on a branch or a SHA — shapes both
    `uvx` and raw.githubusercontent.com accept, and that spec 016 treats as real."""
    r = _run_derivation(_derivation(example), _cfg(tmp_path, {"ref": ref}))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected


@pytest.mark.parametrize("example", EXECUTED, ids=lambda p: p.name)
@requires_bash
def test_a_version_string_elsewhere_in_the_json_does_not_win(tmp_path, example):
    """The reason it reads the KEY and not the file. A grep takes the first match anywhere, so an
    excluded path that happens to contain a version silently decides which gate runs — the same
    'quietly picks a version' failure the step exists to prevent, one layer up."""
    cfg = _cfg(tmp_path, {"excludes": ["vendor/darnlink@v0.1.0"],
                          "ref": "git+https://github.com/txemi/darnlink@v0.22.0"})
    r = _run_derivation(_derivation(example), cfg)
    assert r.stdout.strip() == "v0.22.0", r.stdout + r.stderr


@pytest.mark.parametrize("payload,why", [
    ({"mode": "max"}, "no ref key at all"),
    ({"ref": "darnlink"}, "a ref with no @version"),
    ("{not json", "a file that does not parse"),
])
@pytest.mark.parametrize("example", EXECUTED, ids=lambda p: p.name)
@requires_bash
def test_it_fails_LOUDLY_rather_than_falling_back(tmp_path, example, payload, why):
    """Falling back to a default would be the worst outcome: a green gate at an unknown version. The
    recipe's own default is an ancient tag, so silence here would be actively misleading."""
    r = _run_derivation(_derivation(example), _cfg(tmp_path, payload))
    assert r.returncode != 0, f"{why}: expected a loud failure, got rc=0 / {r.stdout!r}"


@pytest.mark.parametrize("example", EXECUTED, ids=lambda p: p.name)
@requires_bash
def test_a_missing_config_file_fails_too(tmp_path, example):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run_derivation(_derivation(example), empty)
    assert r.returncode != 0, r.stdout


def test_version_is_derived_and_lazy():
    """Two properties in one place because they trade off: hand-written it went seventeen minors
    stale, and eagerly derived it cost a third of the CLI's import time in a pre-commit hook."""
    import darnlink

    assert darnlink.__version__  # resolves
    # …and is discoverable. A PEP 562 `__getattr__` without `__dir__` gives an attribute that answers
    # hasattr but never shows up in dir(), so introspection says it is not there.
    assert "__version__" in dir(darnlink)
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys, darnlink; print('importlib.metadata' in sys.modules)"],
        capture_output=True, text=True)
    assert probe.stdout.strip() == "False", "importing darnlink must not pull importlib.metadata"
