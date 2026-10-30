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


def test_a_markdown_uuid_that_is_also_a_schema_typed_anchor_is_ambiguous(tmp_path, capsys):
    _schemas(tmp_path)
    _hosts_json(tmp_path)
    _w(tmp_path / "other" / "README.md", f"---\nuuid: {H1}\n---\n# Other\n")
    _readme(tmp_path, "../inv/hosts.json#/hosts/0", H1)
    out = _check(tmp_path, capsys)
    assert out["exit_code"] == 2
    assert [f["kind"] for f in out["integrity"]["findings"]] == ["ambiguous"]


def test_a_code_block_that_repeats_a_markdown_uuid_gives_way_to_the_markdown(tmp_path, capsys):
    """Review of #19: a script whose block repeats its README's uuid adopted nothing, so the gate stays green."""
    _w(tmp_path / "a.md", f"---\nuuid: {C1}\n---\n# A\n")
    _w(tmp_path / "b.md", f"see [a](a.md) <!-- uuid: {C1} -->\n")
    _tool(tmp_path)
    assert _check(tmp_path, capsys)["exit_code"] == 0
    _schemas(tmp_path)
    _w(tmp_path / "data" / "card.yaml", f"# yaml-language-server: $schema=../schemas/card.schema.json\n"
                                         f"runs_on:\n  uuid: {C1}\n  link: ../a.md\n")
    out = _refs(tmp_path, capsys)
    assert out["findings"] == [] and out["stats"]["ok"] == 1


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


# --- what the review of 39f1018 found -------------------------------------------------------------


def test_a_pointer_with_a_space_is_written_encoded_and_stays_a_robust_link(tmp_path, capsys):
    _schemas(tmp_path)
    _w(tmp_path / "schemas" / "named.schema.json", json.dumps({"type": "object", "properties": {"hosts": {
        "type": "object", "additionalProperties": {"type": "object", "properties": {
            "uuid": {"$ref": "darnlink_types.schema.json#/$defs/DarnlinkAnchor"}}}}}}))
    _w(tmp_path / "inv" / "h.yaml", "# yaml-language-server: $schema=../schemas/named.schema.json\n"
                                    f"hosts:\n  my host (a):\n    uuid: {H1}\n")
    readme = _readme(tmp_path, "../old.yaml", H1)
    main([str(tmp_path), "--write"])
    capsys.readouterr()
    assert f"[it](../inv/h.yaml#/hosts/my%20host%20%28a%29) <!-- uuid: {H1} -->" in readme.read_text(encoding="utf-8")
    out = _check(tmp_path, capsys)
    assert out["exit_code"] == 0 and out["integrity"]["findings"] == []


def test_a_hostile_json_file_is_reported_and_does_not_abort_the_run(tmp_path, capsys):
    # not "nul.json": on Windows NUL is a reserved device name, and the file would never be written
    _w(tmp_path / "nul_char.json", json.dumps({"$schema": "\u0000x", "a": 1}))
    _w(tmp_path / "deep.json", '{"$schema": "s.json", "a": ' + "[" * 200000 + "]" * 200000 + "}")
    _tool(tmp_path)
    found = collect(tmp_path)
    assert found.count == 1
    assert sorted(f.file for f in found.findings if f.kind == "unreadable-yaml") == ["deep.json", "nul_char.json"]
    _readme(tmp_path, "../tools/deploy.sh", C1)
    assert _check(tmp_path, capsys)["exit_code"] == 0


def test_only_real_line_ends_split_the_leading_comments(tmp_path):
    """A U+2028, U+0085 or form feed inside a comment line no longer cuts the block. YAML itself then refuses the
    block (it reads all three as line breaks or forbids them): that is reported, never a silent loss of the anchor."""
    for sep in ("\u2028", "\u0085", "\x0c"):
        _w(tmp_path / "t.sh", f"#!/bin/sh\n#---\n# note: a{sep}b\n# uuid: {C1}\n#---\n")
        found = collect(tmp_path)
        assert found.anchors or [f.detail for f in found.findings] == ["the #--- block is not YAML"], repr(sep)


def test_crlf_a_bom_and_trailing_spaces_on_the_fence_are_accepted(tmp_path):
    (tmp_path / "w.py").write_bytes(f"﻿# x\r\n#---  \r\n# uuid: {C1}\r\n#---\r\nimport os\r\n".encode("utf-8"))
    assert [(e, u) for items in collect(tmp_path).anchors.values() for e, u in items] == [("", C1)]


def test_a_yaml_file_with_a_typed_uuid_and_the_same_block_counts_once(tmp_path, capsys):
    _w(tmp_path / "schemas" / "one.schema.json", json.dumps({"type": "object", "properties": {
        "uuid": {"$ref": f"{ID}#/$defs/DarnlinkAnchor"}}}))
    _w(tmp_path / "b.yaml", f"# yaml-language-server: $schema=schemas/one.schema.json\n#---\n# uuid: {C1}\n#---\nuuid: {C1}\n")
    assert collect(tmp_path).count == 1
    _readme(tmp_path, "../b.yaml", C1)
    assert _check(tmp_path, capsys)["typed_anchors"] == 1
    assert _refs(tmp_path, capsys)["stats"]["anchors"] == 1


def test_a_yaml_file_with_an_invalid_typed_uuid_and_block_reports_two_distinct_findings(tmp_path, capsys):
    _w(tmp_path / "schemas" / "one.schema.json", json.dumps({"type": "object", "properties": {
        "uuid": {"$ref": f"{ID}#/$defs/DarnlinkAnchor"}}}))
    bad = C1.upper()
    _w(tmp_path / "b.yaml", f"# yaml-language-server: $schema=schemas/one.schema.json\n#---\n# uuid: {bad}\n#---\nuuid: {bad}\n")
    got = sorted(f["pointer"] for f in _refs(tmp_path, capsys)["findings"])
    assert got == ["#---/uuid", "/uuid"]


def test_a_symlink_out_of_the_root_is_not_a_target(tmp_path):
    outside = tmp_path / "outside"
    _tool(outside)
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "linked.sh").symlink_to(outside / "tools" / "deploy.sh")
    except OSError:
        import pytest
        pytest.skip("symlinks are not available here")
    found = collect(root)
    assert found.anchors == {} and [p.name for p in found.out_of_root] == ["linked.sh"]


def test_files_that_declare_no_anchor_give_no_finding(tmp_path, capsys):
    """Review of #19: a JSON config naming a missing schema, a decorative banner between two fences and a file that
    cannot be opened declare nothing, so `yaml-refs` stays at exit 0."""
    _w(tmp_path / "cfg.json", '{"$schema": "./missing.schema.json", "a": 1}')
    _w(tmp_path / "d.sh", "#!/bin/sh\n#---\n# Deploys: the thing: carefully\n#---\necho hi\n")
    _w(tmp_path / "e.json", '{"$schema": "file:///etc/x.json", "b": 2}')
    locked = tmp_path / "locked.sh"
    _w(locked, f"#---\n# uuid: {C1}\n#---\n")
    locked.chmod(0)
    try:
        assert main(["yaml-refs", str(tmp_path)]) == 0
        assert collect(tmp_path).findings == []
    finally:
        locked.chmod(0o644)


def test_a_block_that_tries_to_declare_a_uuid_and_is_not_yaml_is_reported(tmp_path):
    _w(tmp_path / "d.sh", f"#!/bin/sh\n#---\n# uuid: {C1}: oops: here\n#---\n")
    assert [f.detail for f in collect(tmp_path).findings] == ["the #--- block is not YAML"]


def test_a_yaml_file_that_does_not_load_keeps_the_anchor_of_its_block(tmp_path):
    _schemas(tmp_path)
    _w(tmp_path / "x.yaml", f"# yaml-language-server: $schema=schemas/inventory.schema.json\n#---\n# uuid: {C1}\n#---\n"
                            "hosts: [unclosed\n")
    found = collect(tmp_path)
    assert found.anchors == {(tmp_path / "x.yaml").resolve(): [("", C1)]}


def test_a_schema_that_is_not_a_regular_file_is_not_read(tmp_path):
    from darnlink.typed_anchors import _Schemas
    assert _Schemas().get(Path("/dev/null")) == ({}, None)


def test_yaml_refs_writes_the_pointer_fragment_encoded(tmp_path, capsys):
    _schemas(tmp_path)
    _hosts_json(tmp_path, hosts=(("my host", H1),))
    data = json.loads((tmp_path / "inv" / "hosts.json").read_text(encoding="utf-8"))
    data["by name"] = {"my host": {"uuid": H1}}
    del data["hosts"]
    schema = {"type": "object", "properties": {"by name": {"type": "object", "additionalProperties": {
        "type": "object", "properties": {"uuid": {"$ref": "darnlink_types.schema.json#/$defs/DarnlinkAnchor"}}}}}}
    _w(tmp_path / "schemas" / "inventory.schema.json", json.dumps(schema))
    _w(tmp_path / "inv" / "hosts.json", json.dumps(data))
    card = tmp_path / "data" / "card.yaml"
    _w(card, f"# yaml-language-server: $schema=../schemas/card.schema.json\nruns_on:\n  uuid: {H1}\n  link: ../inv/hosts.json\n")
    main(["yaml-refs", str(tmp_path), "--write"])
    capsys.readouterr()
    assert "link: ../inv/hosts.json#/by%20name/my%20host\n" in card.read_text(encoding="utf-8")
    assert main(["yaml-refs", str(tmp_path)]) == 0
