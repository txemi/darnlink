"""The published schema of `darnlink-gate.json` and the `darnlink gate-config` check.

1. the committed `schemas/v1/gate_config.schema.json` is exactly what `gate_config.py` generates;
2. `KEYS` names exactly the keys the bash recipe reads (plus `recipe_sha256`, read by whoever
   downloads it, and the documentation keys), and the PowerShell recipe reads none outside it;
3. the schema and `config_problems` agree, in both directions, on every key and on a pool of values,
   and on real-world config shapes;
4. `darnlink gate-config` only warns: exit 0 with problems, 1 only with --strict.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from darnlink.cli import main
from darnlink.gate_config import (
    KEYS,
    RECIPE_KEYS,
    config_problems,
    file_problems,
    gate_config_schema,
    render_gate_config_schema,
)

ROOT = Path(__file__).resolve().parent.parent
COMMITTED = ROOT / "src" / "darnlink" / "schemas" / "v1" / "gate_config.schema.json"
BASH_RECIPE = ROOT / "recipes" / "darnlink-gate"
PS1_RECIPE = ROOT / "recipes" / "darnlink-gate.ps1"
SHA = "c068f66c166672777f2d63b38ff5d97a61a9ab7288a7c830b8e35520be26c6dd"


def _errors(data):
    # Only the tests that compare against the schema need jsonschema (a dev dependency); the rest run without it.
    jsonschema = pytest.importorskip("jsonschema")
    return list(jsonschema.Draft202012Validator(json.loads(COMMITTED.read_text(encoding="utf-8"))).iter_errors(data))


# --- 1. generated, not hand-written ---------------------------------------------------------------

def test_the_committed_schema_is_the_generated_one():
    assert COMMITTED.read_text(encoding="utf-8") == render_gate_config_schema(), (
        "gate_config.schema.json drifted from darnlink/gate_config.py: run tools/gen_schemas.py")


def test_the_schema_is_a_valid_draft_2020_12_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(gate_config_schema())


# --- 2. the keys are the recipes' keys ------------------------------------------------------------

def test_keys_are_what_the_bash_recipe_reads():
    """A key added to the recipe must be added to KEYS, or the schema calls it unknown; and the other way."""
    text = BASH_RECIPE.read_text(encoding="utf-8")
    read = set(re.findall(r"(?:\$\(|<\()read_cfg(?:_len)? ([a-z_]+)", text))
    assert read == set(RECIPE_KEYS) - {"recipe_sha256"}
    # Every call in code is one of those two forms; a third would hide its key from this test. Calls are
    # counted as `read_cfg <key> ` followed by an argument or `)`, so a mention in a comment does not count.
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    calls = re.findall(r"(\S*)read_cfg(?:_len)? [a-z_]+(?: |\))", code)
    assert calls and all(c.endswith(("$(", "<(")) for c in calls), calls


def test_the_powershell_recipe_reads_exactly_the_keys_bash_reads():
    """Not only no key outside KEYS: the SAME keys as bash. The .ps1 used to skip `dangling`,
    `dangling_max`, `default_branch` and `create_readme_excludes`, so one config gated differently on
    Windows, and the old `<=` here could not see it."""
    text = PS1_RECIPE.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    read = (set(re.findall(r"(?:CfgStr|CfgList|CfgHas|Read-Flag) '([a-z_]+)'", code))
            | set(re.findall(r"\$cfg\.([a-z_]+)", code)))
    assert read == set(RECIPE_KEYS) - {"recipe_sha256"}
    # Every read goes through one of those helpers; the old truthiness reader must not come back.
    assert "CfgOr" not in code


# --- 3. the schema and config_problems agree ------------------------------------------------------

POOL = [
    True, False, None, 0, 1, 2, -1, 0.0, 1.0, 2.5, -0.0, 10 ** 400, "", "0", "1", "true", "True", "TRUE", "false", "False",
    "yes", "no", "on", "off", "Off", "disabled", "warn", "added-lines", "added_lines", "repo", "all",
    "check", "repair", "max", "MAX", "staged", "Staged", "main", "master", "5", "05", "5\n", "-1",
    "git+https://github.com/txemi/darnlink@v0.30.0", SHA, SHA.upper(), SHA + "\n", "x",
    [], ["a"], ["a", "b"], [""], [1], "a", {}, {"a": 1},
]


def _integral_float(value) -> bool:
    return isinstance(value, float) and value.is_integer()


@pytest.mark.parametrize("key", sorted(KEYS))
def test_schema_and_config_problems_agree_on_every_value_of_every_key(key):
    for value in POOL:
        data = {key: value}
        if KEYS[key][0] == "count" and _integral_float(value) and value >= 0:
            # The one documented difference: JSON Schema calls 1.0 an integer, the bash recipe drops it.
            assert not _errors(data) and config_problems(data), (key, value)
            continue
        assert (not _errors(data)) == (not config_problems(data)), (key, value, config_problems(data))


@pytest.mark.parametrize(("key", "value"), [("web", 0.0), ("fail_closed", 0), ("dangling", 1.0),
                                            ("dangling_max", 5.0), ("own_web_max", 1e2)])
def test_a_number_the_bash_recipe_misreads_is_a_warning(key, value):
    """bash prints a JSON number with Python's str(): 0.0 is "0.0", off no list, so `web: 0.0` reads as ON."""
    assert config_problems({key: value})


def test_a_huge_integer_or_a_deep_nesting_is_a_warning_not_a_crash(tmp_path):
    assert config_problems({"dangling_max": 10 ** 400}) == []
    path = tmp_path / "darnlink-gate.json"
    path.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    assert file_problems(path)


# Shapes real-world configs use (documentation keys, notes, booleans, counts): all canonical.
CANONICAL = [
    {},
    {"ref": "git+https://github.com/txemi/darnlink@4afde9f629d43429f0460484b8bee1ca00b56cc8",
     "ref_tag": "v0.28.0", "recipe_sha256": SHA, "excludes": ["worktrees"], "mode": "max",
     "dangling": "repo", "scope": "repo", "web": True, "create_readme": True,
     "forgejo_web": ["https://forge.example.com"]},
    {"ref": "git+https://github.com/txemi/darnlink@7d42686", "ref_comment": "v0.27.0, pinned by SHA",
     "_excluded_debt": ["mirrors"], "mode": "max", "dangling": "repo", "dangling_max": 0,
     "scope": "repo", "default_branch": "master"},
    {"mode": "check", "dangling": "added-lines", "scope": "repo", "create_readme": True,
     "fail_closed": False, "default_branch": "main"},
    {"$schema": "https://github.com/txemi/darnlink/schemas/v1/gate_config", "own_web": ["txemi"],
     "own_web_max": "3", "own_web_from_origin": "yes", "include_mermaid": "0", "ignore_blocks": ["autogrid"],
     "create_readme_excludes": ["mirrors"]},
]


@pytest.mark.parametrize("data", CANONICAL)
def test_canonical_configs_pass_both(data):
    assert _errors(data) == []
    assert config_problems(data) == []


# One wrong thing each: (config, a word the warning must contain).
INVALID = [
    ({"exclude": ["old"]}, "unknown key 'exclude'"),
    ({"fail_closed": "disabled"}, "the recipes stop on it"),
    ({"web": "True"}, "lower case, 'true'"),
    ({"mode": "MAX"}, "is not one of repair, check, max"),
    ({"scope": "Staged"}, "staged, repo"),
    ({"dangling": "sometimes"}, "treat it as off"),
    ({"dangling_max": -1}, "non-negative integer"),
    ({"own_web_max": "five"}, "non-negative integer"),
    ({"default_branch": "False"}, "JSON boolean"),
    ({"default_branch": False}, "not a string"),
    ({"ref": ""}, "non-empty string"),
    ({"excludes": "old"}, "not a list"),
    ({"excludes": ["old", ""]}, "items [1]"),
    ({"recipe_sha256": SHA.upper()}, "lower-case hex"),
    ({"ref_tag": 28}, "not a string"),
    ({"web": None}, "default (off)"),
    ({"dangling": None}, "default (off)"),
    ({"fail_closed": 0.0}, "write true or false"),
]


@pytest.mark.parametrize(("data", "word"), INVALID)
def test_invalid_configs_are_rejected_by_both(data, word):
    assert _errors(data), data
    problems = config_problems(data)
    assert any(word in p for p in problems), problems


def test_a_config_that_is_not_an_object_is_a_problem():
    assert config_problems(["mode", "max"]) and _errors(["mode", "max"])


# --- the file, as the recipes read it -------------------------------------------------------------

def test_file_problems(tmp_path):
    path = tmp_path / "darnlink-gate.json"
    assert file_problems(path) == []                     # absent: every key takes its default
    path.write_text('{"mode": "max",}', encoding="utf-8")
    assert "not valid JSON" in file_problems(path)[0]   # both recipes stop (exit 1)
    path.write_bytes(b'\xef\xbb\xbf{"mode": "max"}')     # a BOM is read as the recipes read it
    assert file_problems(path) == []


# --- 4. the command only warns --------------------------------------------------------------------

def test_gate_config_warns_and_exits_0(tmp_path, capsys):
    (tmp_path / "darnlink-gate.json").write_text('{"exclude": ["old"], "web": "disabled"}', encoding="utf-8")
    assert main(["gate-config", str(tmp_path)]) == 0
    err = capsys.readouterr().err
    assert err.count("darnlink: warning:") == 2
    assert main(["gate-config", str(tmp_path / "darnlink-gate.json"), "--strict"]) == 1


def test_a_missing_file_named_by_hand_fails_with_strict(tmp_path, capsys):
    typo = str(tmp_path / "darnlink-gate.jsno")
    assert main(["gate-config", typo]) == 0
    assert main(["gate-config", typo, "--strict"]) == 1
    assert "no such file" in capsys.readouterr().err


def test_gate_config_on_a_clean_or_missing_file(tmp_path, capsys):
    assert main(["gate-config", str(tmp_path)]) == 0
    assert "nothing to check" in capsys.readouterr().err
    (tmp_path / "darnlink-gate.json").write_text('{"mode": "max", "web": true}', encoding="utf-8")
    assert main(["gate-config", str(tmp_path), "--strict"]) == 0
    assert "warning" not in capsys.readouterr().err
