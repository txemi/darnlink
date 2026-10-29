"""Feature 020, step 2: JSON files and code `#---` blocks as targets, and Markdown links resolving to typed anchors."""
import json
import shutil
from pathlib import Path

import darnlink
from darnlink.cli import main
from darnlink.typed_anchors import code_block, collect

PINNED = Path(darnlink.__file__).parent / "schemas" / "v1" / "darnlink_types.schema.json"
ID = "https://github.com/txemi/darnlink/schemas/v1/darnlink_types"
H1 = "aaaaaaaa-1111-4111-8111-111111111111"
H2 = "bbbbbbbb-2222-4222-8222-222222222222"
C1 = "cccccccc-3333-4333-8333-333333333333"
INVENTORY_SCHEMA = {
    "type": "object",
    "properties": {"hosts": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"},
        "uuid": {"$ref": "darnlink_types.schema.json#/$defs/DarnlinkAnchor"}}}}},
}
CARD_SCHEMA = {"type": "object", "properties": {"runs_on": {"$ref": f"{ID}#/$defs/DarnlinkRef"}}}


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _schemas(root: Path) -> None:
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    shutil.copy(PINNED, root / "schemas" / "darnlink_types.schema.json")
    _w(root / "schemas" / "inventory.schema.json", json.dumps(INVENTORY_SCHEMA))
    _w(root / "schemas" / "card.schema.json", json.dumps(CARD_SCHEMA))


def _hosts_yaml(root: Path, hosts=(("web", H1), ("db", H2)), where="inv/hosts.yaml") -> None:
    body = "".join(f"  - name: {n}\n    uuid: {u}\n" for n, u in hosts)
    _w(root / where, f"# yaml-language-server: $schema=../schemas/inventory.schema.json\nhosts:\n{body}")


def _hosts_json(root: Path, hosts=(("web", H1), ("db", H2)), where="inv/hosts.json", schema="../schemas/inventory.schema.json") -> None:
    _w(root / where, json.dumps({"$schema": schema, "hosts": [{"name": n, "uuid": u} for n, u in hosts]}, indent=1))


def _tool(root: Path, uuid: str = C1, where="tools/deploy.sh", before: str = "#!/bin/sh\n") -> None:
    _w(root / where, f"{before}# Deploys the thing.\n#---\n# uuid: {uuid}\n# owner: someone\n#---\nset -eu\necho hi\n")


def _readme(root: Path, link: str, uuid: str, where="docs/README.md") -> Path:
    _w(root / where, f"---\nuuid: dddddddd-4444-4444-8444-444444444444\n---\n# Docs\n\nSee [it]({link}) <!-- uuid: {uuid} -->.\n")
    return root / where


def _check(root: Path, capsys, *extra) -> dict:
    main(["check", str(root), "--json", *extra])
    return json.loads(capsys.readouterr().out)


def _refs(root: Path, capsys) -> dict:
    main(["yaml-refs", str(root), "--json"])
    return json.loads(capsys.readouterr().out)


# --- the code block -------------------------------------------------------------------------------


def test_the_code_block_is_read_from_the_leading_comments_only():
    assert code_block(f"#!/usr/bin/env python3\n#---\n# uuid: {C1}\n#---\nimport os\n") == f"uuid: {C1}"
    assert code_block(f"import os\n#---\n# uuid: {C1}\n#---\n") is None          # not leading
    assert code_block(f"# a\n#---\n# uuid: {C1}\n") is None                       # never closed
    assert code_block(f"#---\n#  nested:\n#    k: v\n#---\n") == " nested:\n   k: v"


# --- what is collected ----------------------------------------------------------------------------


def test_json_and_code_anchors_are_collected_and_an_untyped_yaml_uuid_is_not(tmp_path):
    _schemas(tmp_path)
    _hosts_json(tmp_path)
    _tool(tmp_path)
    _w(tmp_path / "plain.yaml", f"uuid: {H1}\n")                                       # no schema: not typed
    _w(tmp_path / "remote.json", json.dumps({"$schema": "https://example.org/s.json", "uuid": H2}))
    found = collect(tmp_path)
    got = {(p.relative_to(tmp_path.resolve()).as_posix(), e, u) for p, items in found.anchors.items() for e, u in items}
    assert got == {("inv/hosts.json", "/hosts/0", H1), ("inv/hosts.json", "/hosts/1", H2), ("tools/deploy.sh", "", C1)}
    assert found.findings == []


def test_an_invalid_code_anchor_is_reported_and_not_collected(tmp_path):
    _tool(tmp_path, uuid=C1.upper())
    found = collect(tmp_path)
    assert found.anchors == {}
    [f] = found.findings
    assert (f.kind, f.file) == ("invalid-anchor", "tools/deploy.sh")


def test_excludes_and_the_ignore_marker_keep_a_file_out(tmp_path):
    _tool(tmp_path, where="vendor/x.sh")
    _tool(tmp_path, uuid=H1, before="# <!-- darnlink-ignore-file -->\n")
    assert collect(tmp_path, {"vendor"}).anchors == {}


# --- Markdown links to typed anchors --------------------------------------------------------------


def test_a_markdown_link_to_a_code_file_resolves_and_is_a_file_link(tmp_path, capsys):
    _tool(tmp_path)
    _readme(tmp_path, "../tools/deploy.sh", C1)
    out = _check(tmp_path, capsys)
    assert out["exit_code"] == 0 and out["typed_anchors"] == 1


def test_a_markdown_link_to_a_moved_code_file_is_repaired(tmp_path, capsys):
    _tool(tmp_path, where="bin/deploy.sh")
    readme = _readme(tmp_path, "../tools/deploy.sh", C1)
    assert _check(tmp_path, capsys)["exit_code"] == 2
    assert main([str(tmp_path), "--write"]) == 0
    assert f"[it](../bin/deploy.sh) <!-- uuid: {C1} -->" in readme.read_text(encoding="utf-8")


def test_a_markdown_link_to_a_yaml_element_gets_its_pointer_repaired(tmp_path, capsys):
    _schemas(tmp_path)
    _hosts_yaml(tmp_path, hosts=(("db", H2), ("web", H1)))
    readme = _readme(tmp_path, "../inv/hosts.yaml#/hosts/1", H2)
    [f] = _check(tmp_path, capsys)["integrity"]["findings"]
    assert f["kind"] == "repair" and "#/hosts/0" in f["detail"]
    main([str(tmp_path), "--write"])
    assert f"[it](../inv/hosts.yaml#/hosts/0) <!-- uuid: {H2} -->" in readme.read_text(encoding="utf-8")


def test_a_markdown_link_to_a_moved_json_file_gets_path_and_pointer(tmp_path, capsys):
    _schemas(tmp_path)
    _hosts_json(tmp_path)
    readme = _readme(tmp_path, "../old/hosts.json", H2)
    main([str(tmp_path), "--write"])
    assert f"[it](../inv/hosts.json#/hosts/1) <!-- uuid: {H2} -->" in readme.read_text(encoding="utf-8")


def test_a_readme_uuid_repeated_by_an_untyped_yaml_beside_it_stays_unambiguous(tmp_path, capsys):
    """The guard for the measured case: an `activo.yaml` that repeats its README's uuid, untyped."""
    readme_uuid = "eeeeeeee-5555-4555-8555-555555555555"
    _w(tmp_path / "asset" / "README.md", f"---\nuuid: {readme_uuid}\n---\n# Asset\n")
    _w(tmp_path / "asset" / "activo.yaml", f"uuid: {readme_uuid}\nname: asset\n")
    _readme(tmp_path, "../asset/README.md", readme_uuid)
    assert _check(tmp_path, capsys)["exit_code"] == 0


def test_a_markdown_uuid_that_is_also_a_typed_anchor_is_ambiguous(tmp_path, capsys):
    _tool(tmp_path)
    _w(tmp_path / "other" / "README.md", f"---\nuuid: {C1}\n---\n# Other\n")
    _readme(tmp_path, "../tools/deploy.sh", C1)
    out = _check(tmp_path, capsys)
    assert out["exit_code"] == 2
    assert [f["kind"] for f in out["integrity"]["findings"]] == ["ambiguous"]


def test_an_invalid_code_anchor_does_not_resolve_a_markdown_link(tmp_path, capsys):
    _tool(tmp_path, uuid=C1.upper())
    _readme(tmp_path, "../tools/deploy.sh", C1)
    assert [f["kind"] for f in _check(tmp_path, capsys)["integrity"]["findings"]] == ["unresolvable"]


# --- yaml-refs reaches them too -------------------------------------------------------------------


def test_a_yaml_reference_to_a_json_element_and_to_a_code_file(tmp_path, capsys):
    _schemas(tmp_path)
    _hosts_json(tmp_path, hosts=(("db", H2), ("web", H1)))
    _tool(tmp_path)
    _w(tmp_path / "svc" / "card.yaml", "# yaml-language-server: $schema=../schemas/card.schema.json\n"
                                       f"runs_on:\n  uuid: {H2}\n  link: ../inv/hosts.json#/hosts/1\n")
    _w(tmp_path / "svc" / "job.yaml", "# yaml-language-server: $schema=../schemas/card.schema.json\n"
                                      f"runs_on:\n  uuid: {C1}\n  link: ../tools/deploy.sh\n")
    out = _refs(tmp_path, capsys)
    [f] = out["findings"]
    assert (f["file"], f["kind"], f["new_link"]) == ("svc/card.yaml", "repair", "../inv/hosts.json#/hosts/0")
    assert out["stats"]["ok"] == 1
