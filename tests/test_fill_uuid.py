"""Feature 020, step 3: `yaml-refs` fills the missing `uuid` of a reference from its `link`, with exactly one candidate."""
import json
import shutil
from pathlib import Path

import darnlink
from darnlink.cli import main

PINNED = Path(darnlink.__file__).parent / "schemas" / "v1" / "darnlink_types.schema.json"
ID = "https://github.com/txemi/darnlink/schemas/v1/darnlink_types"
H1 = "aaaaaaaa-1111-4111-8111-111111111111"
H2 = "bbbbbbbb-2222-4222-8222-222222222222"
C1 = "cccccccc-3333-4333-8333-333333333333"
D1 = "dddddddd-4444-4444-8444-444444444444"
INVENTORY_SCHEMA = {
    "type": "object",
    "properties": {"hosts": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"},
        "uuid": {"$ref": "darnlink_types.schema.json#/$defs/DarnlinkAnchor"}}}}},
}
CARD_SCHEMA = {"type": "object", "properties": {
    "runs_on": {"$ref": f"{ID}#/$defs/DarnlinkRef"},
    "also": {"type": "array", "items": {"$ref": f"{ID}#/$defs/DarnlinkRef"}}}}
HEAD = "# yaml-language-server: $schema=../schemas/card.schema.json\n"


def _w(p: Path, text: str, newline: str = "\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.replace("\n", newline).encode("utf-8"))


def _tree(root: Path, hosts=(("web", H1), ("db", H2))) -> Path:
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    shutil.copy(PINNED, root / "schemas" / "darnlink_types.schema.json")
    _w(root / "schemas" / "inventory.schema.json", json.dumps(INVENTORY_SCHEMA))
    _w(root / "schemas" / "card.schema.json", json.dumps(CARD_SCHEMA))
    body = "".join(f"  - name: {n}\n    uuid: {u}\n" for n, u in hosts)
    _w(root / "inv" / "hosts.yaml", f"# yaml-language-server: $schema=../schemas/inventory.schema.json\nhosts:\n{body}")
    _w(root / "docs" / "README.md", f"---\nuuid: {D1}\n---\n# Docs\n")
    _w(root / "tools" / "deploy.sh", f"#!/bin/sh\n#---\n# uuid: {C1}\n#---\necho hi\n")
    return root


def _card(root: Path, body: str, newline: str = "\n") -> Path:
    _w(root / "data" / "card.yaml", HEAD + body, newline)
    return root / "data" / "card.yaml"


def _refs(root: Path, capsys, *extra) -> dict:
    main(["yaml-refs", str(root), "--json", *extra])
    return json.loads(capsys.readouterr().out)


def _kinds(out: dict) -> list:
    return [(f["kind"], f["uuid"]) for f in out["findings"]]


# --- one candidate: fillable, and --write adds exactly one line ------------------------------------------------------


def test_a_link_to_a_markdown_file_is_filled_with_its_frontmatter_uuid(tmp_path, capsys):
    root = _tree(tmp_path)
    card = _card(root, "runs_on:\n  link: ../docs/README.md\n")
    assert _kinds(_refs(root, capsys)) == [("fillable", D1)]
    out = _refs(root, capsys, "--write")
    assert [f["uuid"] for f in out["filled"]] == [D1] and out["findings"] == []
    assert card.read_text(encoding="utf-8") == HEAD + f"runs_on:\n  link: ../docs/README.md\n  uuid: {D1}\n"
    assert main(["yaml-refs", str(root)]) == 0


def test_a_pointer_fragment_names_the_element(tmp_path, capsys):
    root = _tree(tmp_path)
    card = _card(root, "runs_on:\n  link: ../inv/hosts.yaml#/hosts/1  # the db\n")
    _refs(root, capsys, "--write")
    assert f"  link: ../inv/hosts.yaml#/hosts/1  # the db\n  uuid: {H2}\n" in card.read_text(encoding="utf-8")
    assert main(["yaml-refs", str(root)]) == 0


def test_a_code_block_is_a_candidate(tmp_path, capsys):
    root = _tree(tmp_path)
    _card(root, "runs_on:\n  link: ../tools/deploy.sh\n")
    assert _kinds(_refs(root, capsys)) == [("fillable", C1)]


def test_a_file_with_one_element_anchor_and_no_fragment_is_filled_then_its_fragment_repaired(tmp_path, capsys):
    root = _tree(tmp_path, hosts=(("web", H1),))
    card = _card(root, "runs_on:\n  link: ../inv/hosts.yaml\n")
    assert _kinds(_refs(root, capsys)) == [("fillable", H1)]
    _refs(root, capsys, "--write")
    assert _kinds(_refs(root, capsys)) == [("repair", H1)]       # the uuid now says which element: the pointer follows
    _refs(root, capsys, "--write")
    assert f"  link: ../inv/hosts.yaml#/hosts/0\n  uuid: {H1}\n" in card.read_text(encoding="utf-8")
    assert main(["yaml-refs", str(root)]) == 0


def test_list_items_crlf_and_a_last_line_without_newline_are_kept(tmp_path, capsys):
    root = _tree(tmp_path)
    card = _card(root, "also:\n- link: ../docs/README.md\n  # a note\n- link: '../tools/deploy.sh'", newline="\r\n")
    out = _refs(root, capsys, "--write")
    assert sorted(f["uuid"] for f in out["filled"]) == sorted([D1, C1])
    want = HEAD + (f"also:\n- link: ../docs/README.md\n  uuid: {D1}\n  # a note\n"
                   f"- link: '../tools/deploy.sh'\n  uuid: {C1}")
    assert card.read_bytes() == want.replace("\n", "\r\n").encode("utf-8")
    assert main(["yaml-refs", str(root)]) == 0


# --- zero or several candidates, a web link: reported, never written --------------------------------------------------


def _untouched(root: Path, body: str, capsys) -> dict:
    card = _card(root, body)
    before = card.read_bytes()
    out = _refs(root, capsys, "--write")
    assert card.read_bytes() == before and out["filled"] == []
    return out


def test_several_element_anchors_and_no_fragment_are_ambiguous(tmp_path, capsys):
    out = _untouched(_tree(tmp_path), "runs_on:\n  link: ../inv/hosts.yaml\n", capsys)
    assert out["findings"][0]["kind"] == "ambiguous" and "2 candidate anchors" in out["findings"][0]["detail"]


def test_no_anchor_or_no_file_stays_malformed(tmp_path, capsys):
    root = _tree(tmp_path)
    _w(root / "docs" / "plain.md", "# no frontmatter\n")
    assert _untouched(root, "runs_on:\n  link: ../docs/plain.md\n", capsys)["findings"][0]["kind"] == "malformed"
    assert _untouched(root, "runs_on:\n  link: ../docs/gone.md\n", capsys)["findings"][0]["kind"] == "malformed"
    out = _untouched(root, "runs_on:\n  link: ../inv/hosts.yaml#/hosts/7\n", capsys)
    assert "no anchor at #/hosts/7" in out["findings"][0]["detail"]


def test_a_web_link_is_never_filled(tmp_path, capsys):
    out = _untouched(_tree(tmp_path), "runs_on:\n  link: https://example.org/x.md\n", capsys)
    assert out["findings"][0]["kind"] == "malformed" and "web link" in out["findings"][0]["detail"]


def test_a_target_uuid_declared_twice_is_ambiguous(tmp_path, capsys):
    root = _tree(tmp_path)
    _w(root / "other" / "README.md", f"---\nuuid: {D1}\n---\n")
    assert _untouched(root, "runs_on:\n  link: ../docs/README.md\n", capsys)["findings"][0]["kind"] == "ambiguous"


def test_a_uuid_key_left_empty_is_not_filled(tmp_path, capsys):
    out = _untouched(_tree(tmp_path), "runs_on:\n  link: ../docs/README.md\n  uuid:\n", capsys)
    assert out["findings"][0]["kind"] == "malformed"


def test_the_same_text_elsewhere_in_the_file_is_left_to_the_reader(tmp_path, capsys):
    out = _untouched(_tree(tmp_path), "runs_on:\n  link: ../docs/README.md\n# see ../docs/README.md\n", capsys)
    assert out["findings"][0]["kind"] == "fillable"


def test_a_flow_mapping_is_left_to_the_reader(tmp_path, capsys):
    out = _untouched(_tree(tmp_path), "runs_on: {link: ../docs/README.md}\n", capsys)
    assert out["findings"][0]["kind"] == "fillable"
