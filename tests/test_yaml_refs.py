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
