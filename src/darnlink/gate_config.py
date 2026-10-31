"""The keys of `darnlink-gate.json`, their published JSON Schema, and a check that only warns.

`darnlink-gate.json` is read by the two gate recipes (`recipes/darnlink-gate` and
`recipes/darnlink-gate.ps1`), not by the Python package. Until now nothing validated it: an unknown
key or a value of the wrong type was ignored in silence, so a typo (`"exclude"` for `"excludes"`)
configured nothing and the gate stayed green.

`KEYS` below is the single source of truth. Both of these derive from it:

- `gate_config_schema()`: the JSON Schema, written to `schemas/v1/gate_config.schema.json` by
  `tools/gen_schemas.py`, so a consuming repo can pin it;
- `config_problems()`: the same verdict at run time, without a JSON Schema validator (jsonschema is
  only a dev dependency). `darnlink gate-config` prints it as warnings.

`tests/test_gate_config.py` checks that the two agree, in both directions, and that `KEYS` names
exactly the keys the bash recipe reads.

**The schema describes the canonical form**, which is stricter than what the recipes accept. The
recipes lower-case flag values and treat any unknown string as ON (`"disabled"` turns a flag on);
the schema lists only the lower-case spellings the recipes understand. A config the schema rejects
may still run: that is what the warning is for.

Besides the keys the recipes read, three are allowed because consumers already use them to document
the config, and the recipes ignore them: `$schema`, `ref_comment` and `ref_tag`. Any key starting
with `_` is a free note.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

SCHEMA_VERSION = "v1"
SCHEMA_ID = f"https://github.com/txemi/darnlink/schemas/{SCHEMA_VERSION}/gate_config"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
CONFIG_NAME = "darnlink-gate.json"

#: The spellings of a flag the recipes understand, lower case (they lower-case before comparing).
FLAG_OFF = ("", "0", "false", "no", "off")
FLAG_ON = ("1", "true", "yes", "on")
#: `dangling`: off, warn, added-lines, repo, plus the synonyms the bash recipe maps to them.
DANGLING_VALUES = ("off", "", "0", "false", "no", "warn", "added-lines", "added_lines",
                   "repo", "all", "on", "1", "true", "yes")
#: `(?!\n)` before `$`: Python's `$` (what jsonschema runs) also matches before a trailing newline;
#: ECMA-262's does not. Same trick as `darnlink_types.linkml.yaml`.
COUNT_PATTERN = r"^[0-9]+(?!\n)$"
SHA256_PATTERN = r"^[0-9a-f]{64}(?!\n)$"
NOTE_PREFIX = "_"

# kind -> what the value must be. Each kind has its JSON Schema form (_kind_schema) and its run-time
# check (_kind_problem), next to each other so they cannot drift apart unnoticed.
#   flag     boolean, or one of FLAG_OFF + FLAG_ON
#   dangling boolean, or one of DANGLING_VALUES
#   mode     "repair" | "check" | "max"
#   scope    "staged" | "repo"
#   ref      a non-empty string (uvx fails on "")
#   branch   a string that is not "True"/"False" (what a JSON boolean becomes in the bash recipe)
#   count    an integer >= 0, or a string of digits. Written without a decimal point: the bash recipe
#            reads `5.0` as "5.0" and drops it. JSON Schema cannot tell 5.0 from 5 (both are integers to
#            it), so this is the one place where config_problems is stricter than the schema.
#   globs    a list of non-empty strings
#   sha256   64 lower-case hex characters
#   text     a string (documentation keys the recipes ignore)
KEYS: Dict[str, Tuple[str, str]] = {
    "ref": ("ref", "What uvx installs: `git+<url>@<tag or sha>`. Pin a published tag's SHA."),
    "mode": ("mode", "repair, check (default) or max."),
    "scope": ("scope", "staged or repo (default)."),
    "fail_closed": ("flag", "Fail when darnlink cannot run (network, PyPI). Turn it on in CI."),
    "web": ("flag", "mode=max adds a web-check --online pass over cross-repo links."),
    "own_web": ("globs", "Owners you control: their web links without a uuid fail (needs web)."),
    "forgejo_web": ("globs", "Self-hosted Forgejo instances, scheme://host[:port] (needs web)."),
    "own_web_from_origin": ("flag", "Take the own_web owner from the origin remote."),
    "default_branch": ("branch", "The default branch, to tell a pending link from a broken one."),
    "include_mermaid": ("flag", "Also watch the links in mermaid `click` directives (needs web)."),
    "own_web_max": ("count", "How many own_web findings are tolerated (a budget)."),
    "create_readme": ("flag", "A link to a folder without a README fails the gate."),
    "create_readme_excludes": ("globs", "Extra directory globs for the create-readme pass only."),
    "dangling": ("dangling", "Links whose target does not exist: off, warn, added-lines or repo."),
    "dangling_max": ("count", "With dangling=repo, how many are tolerated (a budget). Default 0."),
    "excludes": ("globs", "Directory-name globs to skip."),
    "ignore_blocks": ("globs", "Generated blocks <!-- NAME-start --> ... <!-- NAME-end --> to skip."),
    "recipe_sha256": ("sha256", "sha256 of the recipe, checked by whatever downloads it."),
    "$schema": ("text", "The schema this file follows (for editors). Ignored by the recipes."),
    "ref_comment": ("text", "Why `ref` is pinned where it is. Ignored by the recipes."),
    "ref_tag": ("text", "The tag `ref`'s SHA belongs to. Ignored by the recipes."),
}

#: The keys the recipes read (the rest of KEYS only documents the config).
RECIPE_KEYS = tuple(k for k, (kind, _) in KEYS.items() if kind != "text")


def _kind_schema(kind: str) -> Dict[str, Any]:
    if kind == "flag":
        return {"anyOf": [{"type": "boolean"}, {"enum": list(FLAG_OFF + FLAG_ON)}]}
    if kind == "dangling":
        return {"anyOf": [{"type": "boolean"}, {"enum": list(DANGLING_VALUES)}]}
    if kind == "mode":
        return {"enum": ["repair", "check", "max"]}
    if kind == "scope":
        return {"enum": ["staged", "repo"]}
    if kind == "ref":
        return {"type": "string", "minLength": 1}
    if kind == "branch":
        return {"type": "string", "not": {"enum": ["True", "False"]}}
    if kind == "count":
        return {"anyOf": [{"type": "integer", "minimum": 0},
                          {"type": "string", "pattern": COUNT_PATTERN}]}
    if kind == "globs":
        return {"type": "array", "items": {"type": "string", "minLength": 1}}
    if kind == "sha256":
        return {"type": "string", "pattern": SHA256_PATTERN}
    if kind == "text":
        return {"type": "string"}
    raise ValueError(f"unknown kind {kind!r}")


def _is_int(value: Any) -> bool:
    """An integer as the recipes read it: `5`, not `5.0` (printed as "5.0") nor `true`."""
    return type(value) is int


def _kind_problem(kind: str, value: Any) -> str:
    """Why `value` is not the canonical form of `kind`, or "" if it is."""
    if kind in ("flag", "dangling"):
        allowed = FLAG_OFF + FLAG_ON if kind == "flag" else DANGLING_VALUES
        # Numbers are not canonical: the bash recipe prints 0.0 as "0.0", which is not on the off-list,
        # so `0.0` turns a flag ON. Write true/false.
        if isinstance(value, bool) or (isinstance(value, str) and value in allowed):
            return ""
        if isinstance(value, str) and value.lower() in allowed:
            return f"write it in lower case, {value.lower()!r}"
        if value is None:
            return "is null: the recipes take the default (off); remove the key or write false"
        if not isinstance(value, str):
            # A number can read as ON (bash prints 0.0 as "0.0", not on the off-list); [] reads as off.
            return "is not a boolean or one of its strings (write true or false)"
        if kind == "flag":
            return "is not a boolean; the recipes would read this string as ON"
        return "is not one of off, warn, added-lines or repo; the bash recipe would treat it as off"
    if kind in ("mode", "scope"):
        allowed = ("repair", "check", "max") if kind == "mode" else ("staged", "repo")
        if value in allowed:
            return ""
        return f"is not one of {', '.join(allowed)} (lower case)"
    if kind == "ref":
        return "" if isinstance(value, str) and value else "is not a non-empty string"
    if kind == "branch":
        if not isinstance(value, str):
            return "is not a string (a branch name)"
        return "looks like a JSON boolean, not a branch name" if value in ("True", "False") else ""
    if kind == "count":
        if (_is_int(value) and value >= 0) or (isinstance(value, str) and re.fullmatch(r"[0-9]+", value)):
            return ""
        return "is not a non-negative integer"
    if kind == "globs":
        if not isinstance(value, list):
            return "is not a list of strings"
        bad = [i for i, item in enumerate(value) if not isinstance(item, str) or not item]
        return f"items {bad} are not non-empty strings" if bad else ""
    if kind == "sha256":
        ok = isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        return "" if ok else "is not 64 lower-case hex characters"
    if kind == "text":
        return "" if isinstance(value, str) else "is not a string"
    raise ValueError(f"unknown kind {kind!r}")


def gate_config_schema() -> Dict[str, Any]:
    """The JSON Schema of `darnlink-gate.json`. Deterministic: KEYS order, then dumped with sort_keys."""
    properties = {}
    for key, (kind, description) in KEYS.items():
        properties[key] = {"description": description, **_kind_schema(kind)}
    return {
        "$schema": DRAFT,
        "$id": SCHEMA_ID,
        "title": CONFIG_NAME,
        "description": (
            "GENERATED by tools/gen_schemas.py from darnlink/gate_config.py: do not edit. The "
            "configuration of the darnlink gate recipes, in its canonical form: the recipes accept more "
            "(they lower-case flags and read an unknown string as ON); `darnlink gate-config` warns "
            "about whatever this schema rejects. Every key is optional; keys starting with `_` are notes."
        ),
        "type": "object",
        "properties": properties,
        "patternProperties": {f"^{NOTE_PREFIX}": {}},
        "additionalProperties": False,
    }


def render_gate_config_schema() -> str:
    """The schema as committed: same format as the other schemas in schemas/v1."""
    return json.dumps(gate_config_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def config_problems(data: Any) -> List[str]:
    """What the published schema rejects in a parsed `darnlink-gate.json`, one line each; [] if canonical."""
    if not isinstance(data, dict):
        return ["the config is not a JSON object"]
    problems = []
    for key, value in data.items():
        if key.startswith(NOTE_PREFIX):
            continue
        if key not in KEYS:
            problems.append(f"unknown key {key!r}: the recipes do not read it, so it configures nothing")
            continue
        why = _kind_problem(KEYS[key][0], value)
        if why:
            problems.append(f"{key} = {json.dumps(value, ensure_ascii=False)} {why}")
    return problems


def file_problems(path: Path) -> List[str]:
    """`config_problems` of the file at `path`; [] if it does not exist. Read as the recipes do (utf-8-sig)."""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        return [f"not valid JSON ({exc}): the bash recipe stops, the PowerShell one runs with every default"]
    return config_problems(data)


def run_cli(argv: List[str]) -> int:
    """`darnlink gate-config [PATH] [--strict]`: warn about what the schema rejects. Exit 0 unless --strict."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="darnlink gate-config",
        description=f"check a {CONFIG_NAME} against the published schema (schemas/v1/gate_config.schema.json) "
        "and print each problem as a warning on stderr. Never writes. Exit 0, also with problems, unless --strict.",
    )
    parser.add_argument("path", nargs="?", default=None,
                        help=f"the config file, or a directory that holds one (default: ./{CONFIG_NAME})")
    parser.add_argument("--strict", action="store_true", help="exit 1 if there is any problem")
    args = parser.parse_args(argv)
    path = Path(args.path if args.path is not None else CONFIG_NAME)
    if path.is_dir():
        path = path / CONFIG_NAME
    if not path.is_file():
        if args.path is not None and not Path(args.path).is_dir():
            # A file named by hand that is not there is a typo, not "no config": with --strict a CI step must not go green.
            print(f"darnlink: warning: {path}: no such file", file=sys.stderr)
            return 1 if args.strict else 0
        print(f"darnlink gate-config: no {path}: nothing to check (every key takes its default)", file=sys.stderr)
        return 0
    problems = file_problems(path)
    for problem in problems:
        print(f"darnlink: warning: {path}: {problem}", file=sys.stderr)
    return 1 if (problems and args.strict) else 0
