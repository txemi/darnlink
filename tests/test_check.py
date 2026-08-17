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


def test_87_check_reads_the_tree_exactly_once(tmp_path, capsys, monkeypatch):
    """#87: `check` runs BOTH axes (integrity + strict), and used to pay for a full tree read for
    each — the same files, from disk, twice. This pins the fix at the mechanism, not just the
    symptom: instrument the one shared low-level reader and count real disk reads across a `check`
    run touching several files and several axes at once (a repair candidate, a robustify candidate,
    invalid frontmatter — so the count isn't accidentally low because one axis short-circuited).
    """
    import darnlink.frontmatter_index as fi

    calls: list[str] = []
    orig_read = fi.iter_markdown_files

    def counting_scan_tree(root, excludes=fi.DEFAULT_EXCLUDES):
        from darnlink.frontmatter_edit import read_text_keep_newlines
        files, contents, out_of_root = [], {}, []
        for path in orig_read(root, excludes, out_of_root=out_of_root):
            calls.append(str(path))
            try:
                contents[path] = read_text_keep_newlines(path)
            except Exception:
                continue
            files.append(path)
        return files, contents, out_of_root

    monkeypatch.setattr(fi, "scan_tree", counting_scan_tree)
    # cli.py imported `scan_tree` by name at module load; patch it there too so the CLI actually
    # calls the counting wrapper instead of holding its own reference to the original.
    import darnlink.cli as cli_mod
    monkeypatch.setattr(cli_mod, "scan_tree", counting_scan_tree)

    _w(tmp_path / "target.md", f"---\nuuid: {U}\n---\n# target\n")
    _w(tmp_path / "plain.md", "see [t](target.md)\n")                 # strict-axis candidate
    _w(tmp_path / "bad.md", "---\nuuid: [unterminated\n---\n# bad\n")  # invalid frontmatter, both axes
    _w(tmp_path / "robust.md", f"[t](target.md) <!-- uuid: {U} -->\n")

    main(["check", str(tmp_path), "--json"])

    seen = [c for c in calls if Path(c).name in {"target.md", "plain.md", "bad.md", "robust.md"}]
    assert len(seen) == len(set(seen)), f"a file was walked more than once: {seen!r}"
    assert len(seen) == 4, f"expected exactly 4 files read once each, got: {seen!r}"


def test_87_prescanned_and_own_scan_give_identical_results(tmp_path):
    """The correctness half of #87: `plan_repairs`/`plan_robustify` given a `prescanned` tuple must
    report EXACTLY what they would have reported doing their own scan — sharing the walk must not
    change WHAT is found, only how many times the disk is touched to find it.
    """
    from darnlink.frontmatter_index import build_index, scan_tree
    from darnlink.repair import plan_repairs
    from darnlink.robustify import plan_robustify

    _w(tmp_path / "target.md", f"---\nuuid: {U}\n---\n# target\n")
    _w(tmp_path / "plain.md", "see [t](target.md)\n")
    _w(tmp_path / "robust_stale.md", f"[t](old/target.md) <!-- uuid: {U} -->\n")

    index_own = build_index(tmp_path)
    rep_own = plan_repairs(tmp_path, index_own)
    rob_own = plan_robustify(tmp_path)

    files, contents, out_of_root = scan_tree(tmp_path)
    rep_shared = plan_repairs(tmp_path, index_own, prescanned=(files, contents))
    rob_shared = plan_robustify(tmp_path, prescanned=(files, contents, out_of_root))

    def _detail_set(findings):
        return {(f.kind, str(f.file), f.detail) for f in findings}

    assert _detail_set(rep_own.findings) == _detail_set(rep_shared.findings)
    assert _detail_set(rob_own.findings) == _detail_set(rob_shared.findings)
    assert rep_own.new_content == rep_shared.new_content
    assert rob_own.new_content == rob_shared.new_content


def test_87_robustify_create_readme_does_not_leak_into_the_shared_contents_dict(tmp_path):
    """The mutation-safety guard called out in `plan_robustify`'s own docstring: `--create-readme`
    adds a planned README's content to its internal `contents` — if that dict were the CALLER's
    shared dict (not a copy), a second consumer of the same `prescanned` tuple in the same `check`
    run would see a README that was only ever PLANNED, never written, as if it already existed.
    """
    from darnlink.frontmatter_index import scan_tree
    from darnlink.robustify import plan_robustify

    (tmp_path / "sub").mkdir()
    _w(tmp_path / "A.md", "[dir](sub/)\n")  # a directory link with no README yet

    files, contents, out_of_root = scan_tree(tmp_path)
    contents_before = dict(contents)

    plan_robustify(tmp_path, create_readme=True, prescanned=(files, contents, out_of_root))

    assert contents == contents_before, "the caller's prescanned contents dict was mutated"


def test_87_adversarial_repair_after_robustify_on_the_same_shared_dict_sees_no_phantom(tmp_path):
    """Adversarial variant of the mutation guard above, run in the ORDER a future refactor could use
    (robustify first, repair second) rather than `_run_check`'s current order (repair, then
    robustify). If `plan_robustify` ever aliased the caller's `contents` instead of copying it, a
    phantom README key could leak into a `plan_repairs` call that reuses the SAME dict object
    afterwards. `plan_repairs` only ever reads `contents[f]` for `f` in the `files` list it was
    given — it never iterates `contents.keys()` — so today this cannot surface as a wrong FINDING;
    the assertion instead pins the invariant directly: the dict object plan_repairs actually reads
    from must come back with no extra keys, so the guarantee holds even if a later change makes
    `plan_repairs` (or anything else fed the same tuple) start trusting `contents.keys()`.
    """
    from darnlink.frontmatter_index import build_index, scan_tree
    from darnlink.repair import plan_repairs
    from darnlink.robustify import plan_robustify

    (tmp_path / "sub").mkdir()
    _w(tmp_path / "A.md", "[dir](sub/)\n")  # a directory link with no README yet -> --create-readme plans one

    files, contents, out_of_root = scan_tree(tmp_path)
    index = build_index(tmp_path)

    # robustify FIRST, sharing the exact same `contents` dict object plan_repairs will use next.
    plan_robustify(tmp_path, create_readme=True, prescanned=(files, contents, out_of_root))

    # repair SECOND, reusing the identical dict object (not a fresh scan).
    plan_repairs(tmp_path, index, prescanned=(files, contents))

    assert list(contents.keys()) == [tmp_path / "A.md"], (
        f"a phantom key leaked into the shared contents dict: {sorted(contents.keys())!r}"
    )


def test_87_only_still_scopes_findings_correctly_when_prescanned_is_shared(tmp_path, capsys):
    """#87 combined with feature 010 (`--only`): the ONLY test in the suite that exercises `--only`
    THROUGH `check` (which always passes `prescanned` now) rather than calling `plan_repairs`/
    `plan_robustify` directly. Builds a tree with an integrity candidate (stale robust link) and a
    strict candidate (plain link) in TWO different source files, puts only one of them --only, and
    checks that: (a) the scoped file's findings are reported, (b) the out-of-scope file's equivalent
    findings are suppressed (not silently dropped — `suppressed` counts them), on BOTH axes at once,
    exactly as `--only` promises regardless of whether the run shares one walk or does two.
    """
    target = tmp_path / "target.md"
    _w(target, f"---\nuuid: {U}\n---\n# target\n")
    # scoped.md: in --only. A stale robust link (integrity) AND a plain link to a second, unrelated
    # anchorable target (strict) so both axes have a finding attributable to THIS file.
    target2 = tmp_path / "target2.md"
    _w(target2, f"---\nuuid: {V}\n---\n# target2\n")
    scoped = tmp_path / "scoped.md"
    _w(scoped, f"[t](old/target.md) <!-- uuid: {U} -->\nsee [t2](target2.md)\n")
    # other.md: NOT in --only. Same two shapes, so a full run would report them too, but a scoped
    # run must suppress them rather than report or silently drop them.
    other = tmp_path / "other.md"
    _w(other, f"[t](old/target.md) <!-- uuid: {U} -->\nsee [t2](target2.md)\n")

    code = main(["check", str(tmp_path), "--only", str(scoped), "--json"])
    out = json.loads(capsys.readouterr().out)

    assert code == 2, "the scoped file's stale robust link must still fail the integrity axis"
    integrity_files = {f["file"] for f in out["integrity"]["findings"]}
    strict_files = {f["file"] for f in out["strict"]["findings"]}
    assert any(str(scoped) == f or f.endswith("scoped.md") for f in integrity_files), integrity_files
    assert any(str(scoped) == f or f.endswith("scoped.md") for f in strict_files), strict_files
    assert not any(f.endswith("other.md") for f in integrity_files), \
        f"other.md's finding leaked past --only: {integrity_files}"
    assert not any(f.endswith("other.md") for f in strict_files), \
        f"other.md's finding leaked past --only: {strict_files}"


def test_87_only_plus_prescanned_matches_only_without_prescanned(tmp_path):
    """Direct comparison of the two code paths `plan_repairs`/`plan_robustify` can take with `only`
    set: sharing a `scan_tree` (as `check` now always does) must report and suppress EXACTLY what an
    independent, un-shared scan would — `only` is a report/write filter, `prescanned` is only about
    where the bytes came from, and the two must not interact.
    """
    from darnlink.frontmatter_index import build_index, scan_tree
    from darnlink.repair import plan_repairs
    from darnlink.robustify import plan_robustify

    target = tmp_path / "target.md"
    _w(target, f"---\nuuid: {U}\n---\n# target\n")
    scoped = tmp_path / "scoped.md"
    _w(scoped, f"[t](old/target.md) <!-- uuid: {U} -->\n")
    other = tmp_path / "other.md"
    _w(other, f"[t](old/target.md) <!-- uuid: {U} -->\n")
    only = {scoped.resolve()}

    index_own = build_index(tmp_path)
    rep_own = plan_repairs(tmp_path, index_own, only=only)
    rob_own = plan_robustify(tmp_path, only=only)

    files, contents, out_of_root = scan_tree(tmp_path)
    rep_shared = plan_repairs(tmp_path, index_own, only=only, prescanned=(files, contents))
    rob_shared = plan_robustify(tmp_path, only=only, prescanned=(files, contents, out_of_root))

    def _detail_set(findings):
        return {(f.kind, str(f.file), f.detail) for f in findings}

    assert _detail_set(rep_own.findings) == _detail_set(rep_shared.findings)
    assert _detail_set(rob_own.findings) == _detail_set(rob_shared.findings)
    assert rep_own.suppressed == rep_shared.suppressed
    assert rob_own.suppressed == rob_shared.suppressed
    assert rep_own.new_content == rep_shared.new_content
    assert rob_own.new_content == rob_shared.new_content


def test_87_out_of_root_matches_between_prescanned_and_own_scan(tmp_path):
    """#87 concern: `plan_robustify` used to collect its OWN `out_of_root` list from its OWN
    `iter_markdown_files` call; now, given `prescanned`, it just `.extend()`s the caller's
    already-computed list. Confirms the list `plan_robustify` reports is exactly what an
    independent, un-shared scan of the same tree would have found — same symlink, not dropped,
    not duplicated, not renamed in the process of being threaded through the tuple.
    """
    from darnlink.frontmatter_index import scan_tree
    from darnlink.robustify import plan_robustify

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _w(outside / "external.md", f"---\nuuid: {V}\n---\n# external\n")
    (root / "link.md").symlink_to(outside / "external.md")
    _w(root / "A.md", "# A\n")  # an ordinary in-root file so the tree isn't just the symlink

    rob_own = plan_robustify(root)
    files, contents, out_of_root = scan_tree(root)
    rob_shared = plan_robustify(root, prescanned=(files, contents, out_of_root))

    assert [p.name for p in rob_own.out_of_root] == ["link.md"]
    assert sorted(rob_own.out_of_root) == sorted(rob_shared.out_of_root), (
        rob_own.out_of_root, rob_shared.out_of_root,
    )


def test_87_crlf_frontmatter_survives_the_shared_reader(tmp_path):
    """#87 concern: `scan_tree` reads with `read_text_keep_newlines` (byte-preserving CRLF/BOM)
    where `build_index` used to read with `path.read_text(encoding="utf-8-sig")` (universal-newline,
    CRLF collapsed to LF). The PR's docstring claims YAML parsing doesn't care about the line-ending
    style — verified here with REAL `\\r\\n` bytes on disk (not a simulated string), checked against
    both readers, and through the full `scan_tree` -> `index_from_contents` path end to end.
    """
    from darnlink.frontmatter_edit import read_text_keep_newlines
    from darnlink.frontmatter_index import build_index, read_frontmatter_uuid, scan_tree

    p = tmp_path / "crlf.md"
    p.write_bytes(f"---\r\nuuid: {U}\r\n---\r\n# Title\r\n".encode("utf-8"))

    old_style = p.read_text(encoding="utf-8-sig")   # what build_index used to do
    new_style = read_text_keep_newlines(p)           # what scan_tree does now
    assert "\r\n" not in old_style and "\r" not in old_style  # old reader normalizes newlines
    assert "\r\n" in new_style                                # new reader preserves them verbatim

    assert read_frontmatter_uuid(old_style) == ("valid", U)
    assert read_frontmatter_uuid(new_style) == ("valid", U)

    index = build_index(tmp_path)  # end-to-end through scan_tree + index_from_contents
    assert index.by_uuid.get(U) == p


def test_87_bom_frontmatter_survives_the_shared_reader(tmp_path):
    """Companion to the CRLF test: a REAL leading UTF-8 BOM (`EF BB BF`) on disk, combined with CRLF
    (the common Windows-authored shape). Before this PR there were two independent BOM-stripping
    readers (`path.read_text(encoding="utf-8-sig")` in build_index vs `read_text_keep_newlines`,
    which also uses utf-8-sig but with `newline=""`); confirms both actually strip the BOM the same
    way, and that `scan_tree`'s index still finds the uuid.
    """
    from darnlink.frontmatter_edit import read_text_keep_newlines
    from darnlink.frontmatter_index import build_index, read_frontmatter_uuid

    p = tmp_path / "bom.md"
    raw = b"\xef\xbb\xbf---\r\nuuid: " + U.encode() + b"\r\n---\r\n# Title\r\n"
    p.write_bytes(raw)

    old_style = p.read_text(encoding="utf-8-sig")
    new_style = read_text_keep_newlines(p)
    assert not old_style.startswith("﻿") and not new_style.startswith("﻿"), \
        "both readers must strip the BOM, not just one"

    assert read_frontmatter_uuid(old_style) == ("valid", U)
    assert read_frontmatter_uuid(new_style) == ("valid", U)

    index = build_index(tmp_path)
    assert index.by_uuid.get(U) == p
