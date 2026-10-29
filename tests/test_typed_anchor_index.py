"""Feature 020, step 1: the types recognised by `$id`, and typed anchors in YAML as `yaml-refs` targets."""
import json
import shutil
from pathlib import Path

import darnlink
from darnlink.cli import main
from darnlink.yaml_refs import ANCHOR, REF, TypeRecognizer, anchor_positions

ID = "https://github.com/txemi/darnlink/schemas/v1/darnlink_types"
PINNED = Path(darnlink.__file__).parent / "schemas" / "v1" / "darnlink_types.schema.json"
H1 = "aaaaaaaa-1111-4111-8111-111111111111"
H2 = "bbbbbbbb-2222-4222-8222-222222222222"
UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?!\\n)$"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --- recognition --------------------------------------------------------------------------------


def test_anchor_is_recognised_by_id_by_same_document_and_by_a_pinned_copy(tmp_path):
    shutil.copy(PINNED, tmp_path / "pinned.json")
    rec = TypeRecognizer(tmp_path / "consumer.schema.json")
    assert rec.kind(f"{ID}#/$defs/DarnlinkAnchor") == ANCHOR
    assert rec.kind("https://github.com/txemi/darnlink/schemas/v2/darnlink_types#/$defs/DarnlinkAnchor") == ANCHOR
    assert rec.kind("#/$defs/DarnlinkAnchor") == ANCHOR
    assert rec.kind("pinned.json#/$defs/DarnlinkAnchor") == ANCHOR


def test_anchor_name_under_another_identity_is_not_an_anchor(tmp_path):
    _w(tmp_path / "other.json", json.dumps({"$id": "https://example.org/other", "$defs": {
        "DarnlinkAnchor": {"type": "string"}}}))
    rec = TypeRecognizer(tmp_path / "consumer.schema.json")
    assert rec.kind("other.json#/$defs/DarnlinkAnchor") is None
    assert rec.kind("missing.json#/$defs/DarnlinkAnchor") is None
    assert rec.kind("https://example.org/darnlink_types#/$defs/DarnlinkAnchor") is None
    assert rec.kind(f"{ID}#/$defs/DarnlinkAnchorX") is None


def test_ref_keeps_its_name_match_and_is_also_recognised_by_id(tmp_path):
    rec = TypeRecognizer(tmp_path / "consumer.schema.json")
    assert rec.kind(f"{ID}#/$defs/DarnlinkRef") == REF
    assert rec.kind("anything.json#/$defs/DarnlinkRef") == REF
    assert rec.kind("https://example.org/x/ref.schema.json") == REF


def test_an_inlined_uuid_pattern_is_not_an_anchor():
    schema = {"type": "object", "properties": {"id": {"type": "string", "pattern": UUID_PATTERN}}}
    assert anchor_positions({"id": H1}, schema) == []


def test_anchor_positions_at_any_depth_and_inside_an_optional_slot():
    anchor = {"$ref": "#/$defs/DarnlinkAnchor"}
    schema = {"$defs": {"DarnlinkAnchor": {"type": "string"}}, "type": "object", "properties": {
        "uuid": anchor,
        "hosts": {"type": "array", "items": {"type": "object", "properties": {
            "uuid": {"anyOf": [anchor, {"type": "null"}]}}}}}}
    doc = {"uuid": H1, "hosts": [{"uuid": H2}, {"uuid": None}]}
    assert anchor_positions(doc, schema) == [("/hosts/0/uuid", H2), ("/uuid", H1)]


# --- anchors as targets ---------------------------------------------------------------------------


INVENTORY_SCHEMA = {
    "type": "object",
    "properties": {"hosts": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"},
        "uuid": {"$ref": "darnlink_types.schema.json#/$defs/DarnlinkAnchor"}}}}},
}
CARD_SCHEMA = {
    "type": "object",
    "properties": {"runs_on": {"$ref": f"{ID}#/$defs/DarnlinkRef"}},
}


def _repo(tmp_path: Path, link: str, uuid: str = H2, hosts=(("web", H1), ("db", H2))) -> Path:
    (tmp_path / "schemas").mkdir(parents=True, exist_ok=True)
    shutil.copy(PINNED, tmp_path / "schemas" / "darnlink_types.schema.json")
    _w(tmp_path / "schemas" / "inventory.schema.json", json.dumps(INVENTORY_SCHEMA))
    _w(tmp_path / "schemas" / "card.schema.json", json.dumps(CARD_SCHEMA))
    body = "".join(f"  - name: {n}\n    uuid: {u}\n" for n, u in hosts)
    _w(tmp_path / "inv" / "hosts.yaml",
       f"# yaml-language-server: $schema=../schemas/inventory.schema.json\nhosts:\n{body}")
    _w(tmp_path / "svc" / "card.yaml",
       f"# yaml-language-server: $schema=../schemas/card.schema.json\nruns_on:\n  uuid: {uuid}\n  link: {link}\n")
    return tmp_path


def _json(root: Path, capsys, *extra) -> dict:
    main(["yaml-refs", str(root), "--json", *extra])
    return json.loads(capsys.readouterr().out)


def test_a_reference_to_an_element_anchor_with_its_pointer_is_correct(tmp_path, capsys):
    root = _repo(tmp_path, "../inv/hosts.yaml#/hosts/1")
    out = _json(root, capsys)
    assert out["findings"] == []
    assert out["stats"]["anchors"] == 2 and out["stats"]["ok"] == 1


def test_an_element_that_moved_inside_its_file_gets_its_fragment_repaired(tmp_path, capsys):
    root = _repo(tmp_path, "../inv/hosts.yaml#/hosts/1", hosts=(("db", H2), ("web", H1)))
    [f] = _json(root, capsys)["findings"]
    assert (f["kind"], f["new_link"]) == ("repair", "../inv/hosts.yaml#/hosts/0")
    assert main(["yaml-refs", str(root), "--write"]) == 0
    assert "link: ../inv/hosts.yaml#/hosts/0\n" in (root / "svc" / "card.yaml").read_text(encoding="utf-8")


def test_a_link_without_the_pointer_gets_it_from_the_uuid(tmp_path, capsys):
    root = _repo(tmp_path, "../inv/hosts.yaml")
    [f] = _json(root, capsys)["findings"]
    assert (f["kind"], f["new_link"]) == ("repair", "../inv/hosts.yaml#/hosts/1")


def test_a_moved_file_is_repaired_with_path_and_pointer(tmp_path, capsys):
    root = _repo(tmp_path, "../old/hosts.yaml#/hosts/9")
    [f] = _json(root, capsys)["findings"]
    assert (f["kind"], f["new_link"]) == ("repair", "../inv/hosts.yaml#/hosts/1")


def test_an_uppercase_anchor_is_invalid_and_not_a_target(tmp_path, capsys):
    root = _repo(tmp_path, "../inv/hosts.yaml#/hosts/1", hosts=(("web", H1), ("db", H2.upper())))
    kinds = sorted(f["kind"] for f in _json(root, capsys)["findings"])
    assert kinds == ["invalid-anchor", "unresolvable"]


def test_the_same_anchor_on_two_elements_is_ambiguous(tmp_path, capsys):
    root = _repo(tmp_path, "../inv/hosts.yaml#/hosts/1", hosts=(("web", H2), ("db", H2)))
    [f] = _json(root, capsys)["findings"]
    assert f["kind"] == "ambiguous"


def test_a_schema_with_anchors_and_no_reference_is_still_read(tmp_path, capsys):
    root = _repo(tmp_path, "../inv/hosts.yaml#/hosts/1")
    (root / "svc" / "card.yaml").unlink()
    out = _json(root, capsys)
    assert out["stats"]["with_schema"] == 1 and out["stats"]["anchors"] == 2
