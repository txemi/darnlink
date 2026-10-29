"""`darnlink yaml-refs`: typed {uuid, link} references in YAML files, at the positions the schema declares."""
import json
from pathlib import Path

from darnlink.cli import main
from darnlink.yaml_refs import ref_positions

U = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
V = "11111111-2222-3333-4444-555555555555"

SCHEMA = {
    "$defs": {
        "DarnlinkRef": {"type": "object", "properties": {"uuid": {"type": "string"}, "link": {"type": "string"}}},
        "Card": {"type": "object", "properties": {"home": {"$ref": "#/$defs/DarnlinkRef"},
                                                  "notes": {"type": "object"}}},
    },
    "$ref": "#/$defs/Card",
}


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path, link: str, card_dir: str = "data") -> Path:
    _w(tmp_path / "schemas" / "card.schema.json", json.dumps(SCHEMA))
    _w(tmp_path / "docs" / "target.md", f"---\nuuid: {U}\n---\n# target\n")
    depth = "../" * (card_dir.count("/") + 1)
    _w(tmp_path / card_dir / "card.yaml",
       f"# yaml-language-server: $schema={depth}schemas/card.schema.json\n"
       f"home:\n  uuid: {U}\n  link: {link}\n"
       f"notes:\n  link: not/a/reference.md\n  uuid: {V}\n")
    return tmp_path


def test_positions_come_from_the_schema_not_from_the_shape():
    doc = {"home": {"uuid": U, "link": "x.md"}, "notes": {"uuid": V, "link": "y.md"}}
    assert ref_positions(doc, SCHEMA) == [("/home", {"uuid": U, "link": "x.md"})]


def test_positions_follow_items_and_published_schema_refs():
    schema = {"type": "object", "properties": {"refs": {"type": "array", "items": {
        "$ref": "https://example.org/darnlink/schemas/v1/ref.schema.json"}}}}
    doc = {"refs": [{"uuid": U, "link": "a.md"}, {"uuid": V, "link": "b.md"}]}
    assert [p for p, _ in ref_positions(doc, schema)] == ["/refs/0", "/refs/1"]


def test_correct_reference_is_clean(tmp_path, capsys):
    root = _repo(tmp_path, "../docs/target.md")
    assert main(["yaml-refs", str(root)]) == 0
    assert "1 references in 1 YAML files" in capsys.readouterr().out


def test_moved_target_is_reported_then_repaired_with_write(tmp_path, capsys):
    root = _repo(tmp_path, "../old/target.md")
    card = root / "data" / "card.yaml"
    before = card.read_text(encoding="utf-8")
    assert main(["yaml-refs", str(root)]) == 2
    out = capsys.readouterr().out
    assert "REPAIR       data/card.yaml#/home  ../old/target.md" in out and "-> ../docs/target.md" in out
    assert card.read_text(encoding="utf-8") == before            # check mode never writes
    assert main(["yaml-refs", str(root), "--write"]) == 0
    after = card.read_text(encoding="utf-8")
    assert "  link: ../docs/target.md\n" in after
    assert "  link: not/a/reference.md\n" in after                # an undeclared position is never touched
    assert main(["yaml-refs", str(root)]) == 0


def test_unresolvable_conflict_and_ambiguous_are_broken(tmp_path, capsys):
    root = _repo(tmp_path, "../docs/target.md")
    _w(root / "docs" / "other.md", "# no uuid\n")
    card = root / "data" / "card.yaml"
    card.write_text(card.read_text(encoding="utf-8").replace("../docs/target.md", "../docs/other.md"),
                    encoding="utf-8")
    assert main(["yaml-refs", str(root), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["findings"][0]["kind"] == "conflict"
    _w(root / "docs" / "twin.yaml", f"uuid: {U}\n")              # a YAML top-level uuid is a target too
    assert main(["yaml-refs", str(root), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["findings"][0]["kind"] == "ambiguous"


def test_yaml_target_and_directory_link(tmp_path):
    root = _repo(tmp_path, "../docs")
    (root / "docs" / "target.md").rename(root / "docs" / "README.md")
    assert main(["yaml-refs", str(root)]) == 0                   # a directory link names its README.md
    (root / "docs" / "README.md").unlink()
    (root / "docs").rmdir()
    _w(root / "conf" / "settings.yaml", f"uuid: {U}\nname: x\n")
    assert main(["yaml-refs", str(root), "--write"]) == 0
    assert "  link: ../conf/settings.yaml\n" in (root / "data" / "card.yaml").read_text(encoding="utf-8")


def test_files_without_a_local_schema_are_skipped(tmp_path, capsys):
    _w(tmp_path / "a.yaml", f"home:\n  uuid: {U}\n  link: nowhere.md\n")
    _w(tmp_path / "b.yaml", "# yaml-language-server: $schema=https://example.org/s.json\nhome: {}\n")
    assert main(["yaml-refs", str(tmp_path)]) == 0
    assert "0 references in 0 YAML files with a local schema (2 scanned)" in capsys.readouterr().out


def test_write_never_touches_the_same_link_text_at_an_undeclared_position(tmp_path):
    root = _repo(tmp_path, "../old/target.md")
    card = root / "data" / "card.yaml"
    card.write_text(card.read_text(encoding="utf-8").replace("not/a/reference.md", "../old/target.md"),
                    encoding="utf-8")
    assert main(["yaml-refs", str(root), "--write"]) == 2          # left to the reader, and still reported
    assert card.read_text(encoding="utf-8").count("link: ../old/target.md") == 2


def test_a_broken_unrelated_yaml_does_not_abort_the_run(tmp_path):
    root = _repo(tmp_path, "../docs/target.md")
    _w(root / "other" / "dates.yaml", "d: 2023-13-45\n")             # PyYAML raises ValueError, not YAMLError
    assert main(["yaml-refs", str(root)]) == 0


def test_an_optional_reference_left_empty_is_not_malformed():
    schema = {"properties": {"opt": {"anyOf": [{"$ref": "#/$defs/DarnlinkRef"}, {"type": "null"}]},
                             "either": {"oneOf": [{"$ref": "#/$defs/DarnlinkRef"}, {"type": "string"}]}}}
    assert ref_positions({"opt": None, "either": "plain"}, schema) == []
    assert [p for p, _ in ref_positions({"opt": {"uuid": U, "link": "a.md"}}, schema)] == ["/opt"]


def test_an_unreadable_schema_is_reported_not_skipped(tmp_path, capsys):
    _w(tmp_path / "a.yaml", "# yaml-language-server: $schema=missing.schema.json\nx: 1\n")
    assert main(["yaml-refs", str(tmp_path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["findings"][0]["kind"] == "unreadable-schema"


def test_a_new_link_that_needs_quotes_gets_them(tmp_path):
    root = _repo(tmp_path, "../old/target.md")
    (root / "docs" / "target.md").rename(root / "docs" / "a #b.md")
    assert main(["yaml-refs", str(root), "--write"]) == 0
    assert '  link: "../docs/a #b.md"\n' in (root / "data" / "card.yaml").read_text(encoding="utf-8")


def test_write_does_not_trade_a_flow_mapping_repair_for_an_undeclared_line(tmp_path):
    root = _repo(tmp_path, "../docs/target.md")
    card = root / "data" / "card.yaml"
    card.write_text("# yaml-language-server: $schema=../schemas/card.schema.json\n"
                    f"home: {{uuid: {U}, link: ../old/target.md}}\n"
                    f"notes:\n  uuid: {V}\n  link: ../old/target.md\n", encoding="utf-8")
    before = card.read_text(encoding="utf-8")
    assert main(["yaml-refs", str(root), "--write"]) == 2
    assert card.read_text(encoding="utf-8") == before


def test_a_kept_quote_is_escaped_in_the_new_link(tmp_path):
    root = _repo(tmp_path, "'../old/target.md'")
    (root / "docs" / "target.md").rename(root / "docs" / "it's.md")
    assert main(["yaml-refs", str(root), "--write"]) == 0
    assert "  link: '../docs/it''s.md'\n" in (root / "data" / "card.yaml").read_text(encoding="utf-8")
    assert main(["yaml-refs", str(root)]) == 0


def test_a_backslash_inside_double_quotes_is_escaped(tmp_path):
    root = _repo(tmp_path, '"../old/target.md"')
    (root / "docs" / "target.md").rename(root / "docs" / "a\\b.md")
    assert main(["yaml-refs", str(root), "--write"]) == 0
    assert '  link: "../docs/a\\\\b.md"\n' in (root / "data" / "card.yaml").read_text(encoding="utf-8")
    assert main(["yaml-refs", str(root)]) == 0


def test_an_unreadable_yaml_with_a_schema_is_reported(tmp_path, capsys):
    root = _repo(tmp_path, "../docs/target.md")
    card = root / "data" / "card.yaml"
    card.write_text(card.read_text(encoding="utf-8") + "when: 2023-02-30\n", encoding="utf-8")
    assert main(["yaml-refs", str(root), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["findings"][0]["kind"] == "unreadable-yaml"


def test_an_empty_yaml_with_a_schema_is_not_unreadable(tmp_path):
    _w(tmp_path / "schemas" / "card.schema.json", json.dumps(SCHEMA))
    _w(tmp_path / "data" / "empty.yaml", "# yaml-language-server: $schema=../schemas/card.schema.json\n")
    assert main(["yaml-refs", str(tmp_path)]) == 0


def test_the_fragment_survives_a_repair(tmp_path):
    root = _repo(tmp_path, "../old/target.md#section")
    assert main(["yaml-refs", str(root), "--write"]) == 0
    assert "  link: ../docs/target.md#section\n" in (root / "data" / "card.yaml").read_text(encoding="utf-8")


def test_a_schema_with_a_bom_and_a_modeline_after_the_document_marker(tmp_path):
    root = _repo(tmp_path, "../old/target.md")
    schema = root / "schemas" / "card.schema.json"
    schema.write_text("﻿" + schema.read_text(encoding="utf-8"), encoding="utf-8")
    card = root / "data" / "card.yaml"
    card.write_text("---\n" + card.read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["yaml-refs", str(root)]) == 2                    # found, and reported as a repair
    assert main(["yaml-refs", str(root), "--write"]) == 0
    assert "  link: ../docs/target.md\n" in card.read_text(encoding="utf-8")


def test_a_new_link_with_a_comma_is_quoted_inside_a_flow_mapping(tmp_path):
    root = _repo(tmp_path, "../docs/target.md")
    (root / "docs" / "target.md").rename(root / "docs" / "x,y.md")
    card = root / "data" / "card.yaml"
    card.write_text("# yaml-language-server: $schema=../schemas/card.schema.json\n"
                    f"home: {{\n  uuid: {U},\n  link: ../old/target.md\n}}\n", encoding="utf-8")
    assert main(["yaml-refs", str(root), "--write"]) == 0
    assert '  link: "../docs/x,y.md"\n' in card.read_text(encoding="utf-8")
    assert main(["yaml-refs", str(root)]) == 0


def test_an_optional_reference_with_a_misspelt_key_is_malformed(tmp_path, capsys):
    root = _repo(tmp_path, "../docs/target.md")
    schema = {"$defs": SCHEMA["$defs"], "properties": {"opt": {"anyOf": [{"$ref": "#/$defs/DarnlinkRef"},
                                                                          {"type": "null"}]}}}
    _w(root / "schemas" / "opt.schema.json", json.dumps(schema))
    _w(root / "data" / "opt.yaml", f"# yaml-language-server: $schema=../schemas/opt.schema.json\n"
                                   f"opt:\n  uuid: {U}\n  lnk: ../docs/target.md\n")
    assert main(["yaml-refs", str(root), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["findings"][0]["kind"] == "malformed"


def test_an_entity_with_a_uuid_in_another_object_alternative_is_not_a_reference():
    schema = {"properties": {"o": {"anyOf": [{"$ref": "#/$defs/DarnlinkRef"},
                                             {"type": "object", "properties": {"uuid": {}, "name": {}}}]}}}
    assert ref_positions({"o": {"uuid": U, "name": "x"}}, schema) == []
    assert [p for p, _ in ref_positions({"o": {"uuid": U, "link": "a.md"}}, schema)] == ["/o"]


def test_write_leaves_the_file_alone_when_the_result_would_not_load(tmp_path, monkeypatch):
    import darnlink.yaml_refs as yr
    root = _repo(tmp_path, "../old/target.md")
    card = root / "data" / "card.yaml"
    before = card.read_text(encoding="utf-8")
    monkeypatch.setattr(yr, "_rewrite_is_exact", lambda original, text, written: False)
    assert main(["yaml-refs", str(root), "--write"]) == 2
    assert card.read_text(encoding="utf-8") == before


def test_an_empty_link_is_malformed(tmp_path, capsys):
    root = _repo(tmp_path, "''")
    (root / "data" / "README.md").write_text(f"---\nuuid: {U}\n---\n", encoding="utf-8")
    assert main(["yaml-refs", str(root), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["findings"][0]["kind"] == "malformed"


def test_write_never_rewrites_a_literal_twin_of_an_escaped_link(tmp_path):
    root = _repo(tmp_path, '"../old/targe\\x74.md"')
    card = root / "data" / "card.yaml"
    card.write_text(card.read_text(encoding="utf-8") + "text: |\n  link: ../old/target.md\n", encoding="utf-8")
    before = card.read_text(encoding="utf-8")
    assert main(["yaml-refs", str(root), "--write"]) == 2          # the repair is left to the reader
    assert card.read_text(encoding="utf-8") == before


def test_write_checks_the_new_link_at_its_own_position(tmp_path):
    root = _repo(tmp_path, '"../old/targe\\x74.md"')
    card = root / "data" / "card.yaml"
    card.write_text(card.read_text(encoding="utf-8").replace("not/a/reference.md", "../old/target.md"),
                    encoding="utf-8")
    before = card.read_text(encoding="utf-8")
    assert main(["yaml-refs", str(root), "--write"]) == 2          # the undeclared twin would be the one rewritten
    assert card.read_text(encoding="utf-8") == before


def test_a_yaml_that_is_not_utf8_is_reported(tmp_path, capsys):
    root = _repo(tmp_path, "../old/target.md")
    card = root / "data" / "card.yaml"
    card.write_bytes(card.read_bytes() + "name: Jos\u00e9\n".encode("latin-1"))
    assert main(["yaml-refs", str(root), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["findings"][0]["kind"] == "unreadable-yaml"


def test_a_yaml_whose_schema_declares_no_reference_need_not_load(tmp_path):
    _w(tmp_path / "schemas" / "plain.schema.json", json.dumps({"type": "object"}))
    _w(tmp_path / "data" / "multi.yaml", "# yaml-language-server: $schema=../schemas/plain.schema.json\n"
                                         "a: !Ref x\n---\nb: 2\n")
    assert main(["yaml-refs", str(tmp_path)]) == 0


def test_write_never_rewrites_an_undeclared_twin_of_an_escaped_link(tmp_path):
    root = _repo(tmp_path, '"../old/targe\\x74.md"')
    card = root / "data" / "card.yaml"
    card.write_text(card.read_text(encoding="utf-8").replace("not/a/reference.md", "../old/target.md")
                    .replace(f"  uuid: {V}\n", ""), encoding="utf-8")      # notes: a bare `link:` mapping, not declared
    before = card.read_text(encoding="utf-8")
    assert main(["yaml-refs", str(root), "--write"]) == 2
    assert card.read_text(encoding="utf-8") == before


def test_a_deep_reference_is_still_found():
    from darnlink.yaml_refs import mentions_ref_type
    node = {"$ref": "#/$defs/DarnlinkRef"}
    for _ in range(40):
        node = {"properties": {"p": node}}
    assert mentions_ref_type(node)
    assert not mentions_ref_type({"properties": {"p": {"type": "string"}}})


def test_pointers_resolve_escapes_and_indexes():
    from darnlink.yaml_refs import _at
    doc = {"a/b": [{"x~y": 1}]}
    assert _at(doc, "/a~1b/0/x~0y") == 1
    assert _at(doc, "") is doc
    assert _at(doc, "/a~1b/5") is None
