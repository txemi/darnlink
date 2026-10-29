"""Feature 019: darnlink publishes the `DarnlinkAnchor` and `DarnlinkRef` types, LinkML first.

Three promises are checked here:

1. the committed JSON Schema is exactly what `tools/gen_schemas.py` generates from the LinkML source
   (skipped when `linkml` is not installed; it is in the `dev` extra);
2. the JSON Schema accepts and rejects what the spec says, validated the way a consumer would use
   a pinned copy: registered under its `$id`, never fetched;
3. both schema files ship inside the built wheel, not only in the source tree.
"""
import importlib.util
import json
import shutil
import subprocess
import zipfile
from importlib import resources
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
V1_ID = "https://github.com/txemi/darnlink/schemas/v1/darnlink_types"
FILES = ("darnlink_types.linkml.yaml", "darnlink_types.schema.json")
GOOD_UUID = "0ef3169a-bce1-4a6b-8bc4-7850ceade107"


def _published() -> dict:
    text = resources.files("darnlink").joinpath("schemas/v1/darnlink_types.schema.json").read_text(
        encoding="utf-8")
    return json.loads(text)


def _gen_schemas():
    spec = importlib.util.spec_from_file_location("gen_schemas", ROOT / "tools" / "gen_schemas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- 1. the JSON is generated, not hand-written --------------------------------------------------

def test_the_shipped_json_schema_is_a_fresh_generation_of_the_linkml_source():
    pytest.importorskip("linkml")
    gen = _gen_schemas()
    assert gen.JSON_OUTPUT.read_text(encoding="utf-8") == gen.generate(), (
        "darnlink_types.schema.json drifted from its LinkML source: run tools/gen_schemas.py")


def test_the_id_is_versioned_and_both_types_are_reachable_under_defs():
    schema = _published()
    assert schema["$id"] == V1_ID and "/v1/" in schema["$id"]
    assert {"DarnlinkAnchor", "DarnlinkRef"} <= set(schema["$defs"])
    assert schema["$defs"]["DarnlinkRef"]["properties"]["uuid"]["$ref"] == "#/$defs/DarnlinkAnchor"
    assert "metamodel_version" not in schema


# --- 2. what the types accept and reject ---------------------------------------------------------

def _validator(definition: str):
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    published = _published()
    registry = referencing.Registry().with_resource(
        V1_ID, referencing.Resource.from_contents(published))
    wrapper = {"$schema": published["$schema"], "$ref": f"{V1_ID}#/$defs/{definition}"}
    cls = jsonschema.validators.validator_for(published)
    cls.check_schema(published)
    return cls(wrapper, registry=registry)


@pytest.mark.parametrize("instance", [
    {"link": "../docs/target.md", "uuid": GOOD_UUID},
    {"link": "notes.md#a-section", "uuid": GOOD_UUID},
    {"link": "assets/diagram/", "uuid": GOOD_UUID},
    {"link": "https://example.test/owner/repo/src/branch/main/README.md", "uuid": GOOD_UUID},
    {"link": "http://example.test/page", "uuid": GOOD_UUID},
], ids=["relative", "fragment", "directory", "https-url", "http-url"])
def test_a_valid_ref_validates(instance):
    assert list(_validator("DarnlinkRef").iter_errors(instance)) == []


@pytest.mark.parametrize("instance", [
    {"link": "../docs/target.md"},
    {"uuid": GOOD_UUID},
    {"link": "../docs/target.md", "uuid": GOOD_UUID.upper()},
    {"link": "../docs/target.md", "uuid": GOOD_UUID[:-1]},
    {"link": "../docs/target.md", "uuid": GOOD_UUID, "title": "extra"},
    {"link": "/abs/target.md", "uuid": GOOD_UUID},
    {"link": "#only-a-fragment", "uuid": GOOD_UUID},
    {"link": "ftp://example.test/x.md", "uuid": GOOD_UUID},
    {"link": "", "uuid": GOOD_UUID},
    GOOD_UUID,
], ids=["missing-uuid", "missing-link", "uppercase-uuid", "short-uuid", "extra-property",
        "absolute-path", "bare-fragment", "other-scheme", "empty-link", "not-an-object"])
def test_an_invalid_ref_is_rejected(instance):
    assert list(_validator("DarnlinkRef").iter_errors(instance)) != []


def test_the_anchor_is_lowercase_canonical_only():
    anchor = _validator("DarnlinkAnchor")
    assert anchor.is_valid(GOOD_UUID)
    for bad in (GOOD_UUID.upper(), "{" + GOOD_UUID + "}", GOOD_UUID.replace("-", ""), 42):
        assert not anchor.is_valid(bad), bad


def test_yaml_refs_recognises_a_ref_into_a_pinned_copy():
    """A consumer that pins the file and points a field at its `DarnlinkRef` is already seen by
    `darnlink yaml-refs` (by definition name); the anchor definition is not a reference."""
    from darnlink.yaml_refs import is_ref_type
    assert is_ref_type("../schemas/darnlink_types.schema.json#/$defs/DarnlinkRef")
    assert not is_ref_type("../schemas/darnlink_types.schema.json#/$defs/DarnlinkAnchor")


# --- 3. package data -----------------------------------------------------------------------------

def test_the_schema_files_are_present_under_the_package():
    base = resources.files("darnlink").joinpath("schemas/v1")
    for name in FILES:
        assert base.joinpath(name).is_file(), name


def test_the_schema_files_ship_in_the_built_wheel(tmp_path):
    """`importlib.resources` resolves to the source tree in a development install, so it cannot
    prove the wheel carries the files. Building one does."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed: cannot build the wheel")
    subprocess.run([uv, "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)],
                   check=True, capture_output=True, text=True)
    (wheel,) = tmp_path.glob("darnlink-*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    for name in FILES:
        assert f"darnlink/schemas/v1/{name}" in names, name
