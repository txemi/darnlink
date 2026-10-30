#!/usr/bin/env python3
"""Regenerate the published JSON Schema of the darnlink types from their LinkML source (feature 019).

The LinkML file is the single source of truth; the JSON Schema next to it is a build product that is
committed so consumers can pin it without installing LinkML. This script is the only way that file
is written, and `tests/test_typed_anchor_and_link.py` fails if the committed copy drifts from it.

What `gen-json-schema` does NOT give us, and the deterministic fixes applied here
---------------------------------------------------------------------------------
1. **A LinkML `type` gets no `$defs` entry.** The generator inlines a type where a slot uses it
   (`{"type": "string", "pattern": ...}`), so `DarnlinkAnchor` would exist only as a copy of its
   pattern inside `DarnlinkRef.uuid`, and a consumer could not `$ref` it. We add
   `$defs/DarnlinkAnchor` from the LinkML type itself, and replace every inlined copy (a property
   whose LinkML range is that type) with a `$ref` to it. Before replacing, the inlined copy is
   checked to be exactly the type's JSON form, so a generator change fails here instead of shipping
   silently.
2. **`metamodel_version` names the generator, not the schema.** It changes with every LinkML
   upgrade, which would make the committed file drift without any change to the types. It is
   dropped; `version` (the schema's own) is kept.
3. **Key order.** Output is `json.dumps(..., indent=2, sort_keys=True)` plus a trailing newline, so
   the bytes depend only on the content.

Usage:
    uv run --extra dev python tools/gen_schemas.py           # rewrite the JSON Schema
    uv run --extra dev python tools/gen_schemas.py --check   # exit 1 if the committed copy drifted
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "src" / "darnlink" / "schemas" / "v1"
LINKML_SOURCE = SCHEMA_DIR / "darnlink_types.linkml.yaml"
JSON_OUTPUT = SCHEMA_DIR / "darnlink_types.schema.json"

# The only base type the published types use today. Another one is a deliberate change: add its
# JSON form here rather than guess it.
_JSON_FORM_OF_BASE_TYPE = {"string": "string"}


def _type_json(type_def) -> dict:
    """The JSON Schema form of a LinkML `type` declared in this schema (typeof string + pattern)."""
    base = str(type_def.typeof)
    if base not in _JSON_FORM_OF_BASE_TYPE:
        raise SystemExit(f"gen_schemas: type {type_def.name} is typeof {base!r}; only "
                         f"{sorted(_JSON_FORM_OF_BASE_TYPE)} are supported")
    form = {"type": _JSON_FORM_OF_BASE_TYPE[base]}
    if type_def.pattern:
        form["pattern"] = type_def.pattern
    return form


def generate(source: Path = LINKML_SOURCE) -> str:
    """Return the JSON Schema text for `source`. Pure: reads the LinkML file, writes nothing."""
    from linkml.generators.jsonschemagen import JsonSchemaGenerator
    from linkml_runtime.utils.schemaview import SchemaView

    schema = json.loads(JsonSchemaGenerator(str(source)).serialize())
    view = SchemaView(str(source))
    defs = schema.setdefault("$defs", {})

    own_types = {name: t for name, t in view.all_types(imports=False).items()}
    for name, type_def in own_types.items():
        if name in defs:
            raise SystemExit(f"gen_schemas: the generator already emits $defs/{name}; "
                             "drop the post-processing for it")
        entry = {"title": str(name), **_type_json(type_def)}
        if type_def.description:
            entry["description"] = type_def.description
        defs[str(name)] = entry

    for class_name in view.all_classes(imports=False):
        props = defs[str(class_name)].get("properties", {})
        for slot in view.class_induced_slots(class_name):
            if slot.range not in own_types:
                continue
            inlined = props[slot.name]
            expected = _type_json(own_types[slot.range])
            got = {k: v for k, v in inlined.items() if k != "description"}
            if got != expected:
                raise SystemExit(f"gen_schemas: {class_name}.{slot.name} was generated as {got}, "
                                 f"expected the inlined {slot.range} {expected}")
            replaced = {"$ref": f"#/$defs/{slot.range}"}
            if "description" in inlined:
                replaced["description"] = inlined["description"]
            props[slot.name] = replaced

    schema.pop("metamodel_version", None)
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the committed JSON Schema differs")
    args = parser.parse_args(argv)
    fresh = generate()
    current = JSON_OUTPUT.read_text(encoding="utf-8") if JSON_OUTPUT.exists() else None
    if args.check:
        if current != fresh:
            print(f"{JSON_OUTPUT.relative_to(ROOT)} is stale: run tools/gen_schemas.py",
                  file=sys.stderr)
            return 1
        return 0
    if current != fresh:
        JSON_OUTPUT.write_text(fresh, encoding="utf-8")
        print(f"wrote {JSON_OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
