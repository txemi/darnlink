"""Feature 007: `darnlink check` — report-only gate running both axes with distinguishable exit codes.

Acceptance (from specs/007-darnlink-check/spec.md):
- broken robust link only            -> exit 2 (integrity)
- un-anchored plain link only        -> exit 3 (strict)
- both                               -> exit 2 (integrity precedence)
- clean                              -> exit 0
- never writes (checksums unchanged)
"""
import hashlib
import json
from pathlib import Path

import pytest

from darnlink.cli import main

U = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
V = "11111111-2222-3333-4444-555555555555"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _checksums(root: Path):
    return {p: hashlib.sha1(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*.md"))}


def _clean_tree(tmp_path: Path) -> None:
    # target present, inbound robust link with the correct path -> nothing to repair, nothing to robustify
    _w(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", f"See [B](B.md) <!-- uuid: {U} -->\n")


def test_clean_tree_exits_0(tmp_path):
    _clean_tree(tmp_path)
    assert main(["check", str(tmp_path)]) == 0


def test_check_output_is_cp1252_safe(tmp_path, capsys):
    # Regression: `darnlink check` printed a summary with '->' (was U+2192 '→'), which a Windows
    # cp1252 console (the Spanish-Windows default) cannot encode -> UnicodeEncodeError -> the gate
    # exited non-zero on ENCODING, not on links (a false red for the whole Windows fleet). The output
    # must be encodable in cp1252 so the gate never crashes there.
    _clean_tree(tmp_path)
    main(["check", str(tmp_path)])
    out = capsys.readouterr().out
    out.encode("cp1252")  # raises UnicodeEncodeError if any char is outside cp1252


def test_broken_robust_link_exits_2(tmp_path):
    # B lives in new/, but A still points at old/ (path stale) — a repairable/broken robust link.
    _w(tmp_path / "new" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", f"See [B](old/B.md) <!-- uuid: {U} -->\n")  # no un-anchored plain links
    assert main(["check", str(tmp_path)]) == 2


def test_unresolvable_robust_link_exits_2(tmp_path):
    # robust link whose uuid is in no file at all -> integrity failure
    _w(tmp_path / "A.md", f"See [X](X.md) <!-- uuid: {V} -->\n")
    assert main(["check", str(tmp_path)]) == 2


def test_unanchored_plain_link_exits_3(tmp_path):
    # target is anchorable (has frontmatter+uuid) but the link is plain -> strict failure only
    _w(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", "See [B](B.md)\n")  # plain, no uuid comment; no broken robust links
    assert main(["check", str(tmp_path)]) == 3


def test_both_axes_fail_integrity_precedence_exits_2(tmp_path):
    _w(tmp_path / "new" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", f"stale [B](old/B.md) <!-- uuid: {U} -->\n")  # integrity fail
    _w(tmp_path / "C.md", f"---\nuuid: {V}\n---\n# C\n")
    _w(tmp_path / "D.md", "plain [C](C.md)\n")                          # strict fail
    assert main(["check", str(tmp_path)]) == 2  # integrity wins


def test_check_never_writes(tmp_path):
    _w(tmp_path / "new" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", f"stale [B](old/B.md) <!-- uuid: {U} -->\n")
    _w(tmp_path / "D.md", f"---\nuuid: {V}\n---\n")
    _w(tmp_path / "E.md", f"plain [D](D.md)\n")
    before = _checksums(tmp_path)
    main(["check", str(tmp_path)])
    assert _checksums(tmp_path) == before  # report-only: not one byte changed


def test_json_separates_the_two_axes(tmp_path, capsys):
    _w(tmp_path / "new" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", f"stale [B](old/B.md) <!-- uuid: {U} -->\n")
    _w(tmp_path / "C.md", f"---\nuuid: {V}\n---\n# C\n")
    _w(tmp_path / "D.md", "plain [C](C.md)\n")
    code = main(["check", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2
    assert out["exit_code"] == 2
    assert out["integrity"]["failed"] is True
    assert out["strict"]["failed"] is True          # both axes reported even though exit is integrity's
    assert out["strict"]["robustify"] >= 1


def test_not_a_directory_exits_1(tmp_path):
    missing = tmp_path / "nope"
    assert main(["check", str(missing)]) == 1


def test_bad_flag_exits_1_not_2(tmp_path):
    # argparse defaults to exit 2 on a parse error, which would collide with "integrity failure";
    # `check` must use 1 for usage errors (Copilot review, PR #6).
    with pytest.raises(SystemExit) as e:
        main(["check", str(tmp_path), "--nonexistent-flag"])
    assert e.value.code == 1


def test_json_includes_invalid_frontmatter_details(tmp_path, capsys):
    # invalid YAML frontmatter -> integrity failure; the --json must carry the file, not just a count.
    _w(tmp_path / "bad.md", "---\nuuid: [unterminated\n---\n# bad\n")
    code = main(["check", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2
    assert any("bad.md" in p for p in out["integrity"]["invalid_frontmatter_files"])
    assert any(f["kind"] == "invalid_frontmatter" and "bad.md" in f["file"]
               for f in out["integrity"]["findings"])


def test_json_strict_axis_lists_invalid_frontmatter(tmp_path, capsys):
    # a plain link whose TARGET has invalid frontmatter surfaces on the strict axis too; the --json
    # must carry the file list there as well (not just a count).
    _w(tmp_path / "bad.md", "---\nuuid: [unterminated\n---\n# bad\n")
    _w(tmp_path / "A.md", "see [bad](bad.md)\n")  # plain link to the invalid target
    main(["check", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert any("bad.md" in p for p in out["strict"]["invalid_frontmatter_files"])
    assert any(f["kind"] == "invalid_frontmatter" and "bad.md" in f["file"]
               for f in out["strict"]["findings"])
