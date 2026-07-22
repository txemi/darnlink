"""Feature 010: write scope — `--only` / `--only-from` / `--no-target-writes`.

Acceptance (from specs/010-write-scope/spec.md):
1. motivating case — a file whose target lives in another subtree is anchored (dir-scan skips it)
2. several files at once
3. the guarantee — nothing outside the write scope changes (hash the tree)
4. target writes are visible (reported) and refusable (--no-target-writes)
5. repair, narrowed — outbound repaired; report says inbound elsewhere not considered
6. guard rails — bad --only path exits 1
7. piped list — --only-from - == repeated --only
8. regression — no --only is byte-identical; `darnlink some/file.md` still errors
"""
import hashlib
from pathlib import Path

import pytest

from darnlink.cli import main
from darnlink.frontmatter_edit import read_uuid_from_content
from darnlink.links import find_robust_links
from darnlink.report import Kind
from darnlink.robustify import plan_robustify
from darnlink.scope import ScopeError, resolve_write_scope

U = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
V = "11111111-2222-3333-4444-555555555555"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _tree_hashes(root: Path):
    return {p.relative_to(root).as_posix(): hashlib.sha1(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.md"))}


# --- 1. the motivating case: target in another subtree, only the source is written ---------------

def test_only_anchors_link_whose_target_is_in_another_subtree(tmp_path):
    _w(tmp_path / "y" / "B.md", f"---\nuuid: {U}\n---\n# B\n")   # target already has a uuid
    _w(tmp_path / "x" / "A.md", "See [B](../y/B.md) plain.\n")
    a = tmp_path / "x" / "A.md"

    rc = main([str(tmp_path), "--robustify", "--write", "--only", str(a)])
    assert rc == 0
    links = find_robust_links(a.read_text())
    assert len(links) == 1 and links[0].uuid == U          # anchored, reusing the target's uuid
    # target byte-identical (it already had a uuid — no write needed)
    assert (tmp_path / "y" / "B.md").read_text() == f"---\nuuid: {U}\n---\n# B\n"


def test_dir_scan_of_the_subtree_alone_cannot_anchor_it(tmp_path):
    # Contrast: scanning only x/ (today's advice) never indexes y/B.md, so the target is unknown.
    _w(tmp_path / "y" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "x" / "A.md", "See [B](../y/B.md) plain.\n")
    result = plan_robustify(tmp_path / "x")
    assert result.new_content == {}                        # nothing anchored
    assert any(f.kind is Kind.OUT_OF_SCOPE for f in result.findings)   # FR-009: honest kind
    assert not any(f.kind is Kind.NO_FRONTMATTER for f in result.findings)  # NOT the wrong one


# --- 2. several files at once --------------------------------------------------------------------

def test_only_multiple_files(tmp_path):
    _w(tmp_path / "t1" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "t2" / "C.md", f"---\nuuid: {V}\n---\n# C\n")
    _w(tmp_path / "A.md", "[B](t1/B.md) and [C](t2/C.md)\n")
    _w(tmp_path / "D.md", "[C](t2/C.md)\n")                 # NOT in scope — must stay plain
    a = tmp_path / "A.md"

    rc = main([str(tmp_path), "--robustify", "--write", "--only", str(a)])
    assert rc == 0
    assert len(find_robust_links(a.read_text())) == 2
    assert find_robust_links((tmp_path / "D.md").read_text()) == []   # untouched


# --- 3. the guarantee: nothing outside the write scope changes ------------------------------------

def test_nothing_outside_scope_is_written(tmp_path):
    _w(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "keep" / "A.md", "[B](../B.md)\n")
    # many other robustifiable links elsewhere — a repo-wide run would rewrite them all
    for i in range(5):
        _w(tmp_path / "other" / f"O{i}.md", "[B](../B.md)\n")
    before = _tree_hashes(tmp_path)
    a = tmp_path / "keep" / "A.md"

    main([str(tmp_path), "--robustify", "--write", "--only", str(a)])
    after = _tree_hashes(tmp_path)

    changed = {k for k in before if before[k] != after[k]}
    assert changed == {"keep/A.md"}                         # exactly the scoped file, nothing else


def test_idempotent_under_only(tmp_path):
    _w(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", "[B](B.md)\n")
    a = tmp_path / "A.md"
    main([str(tmp_path), "--robustify", "--write", "--only", str(a)])
    second = plan_robustify(tmp_path, only={a.resolve()})
    assert second.new_content == {}


# --- 4. target writes are visible and refusable --------------------------------------------------

def test_target_write_is_reported_and_happens_by_default(tmp_path):
    _w(tmp_path / "y" / "B.md", "---\ntitle: B\n---\n# B\n")  # frontmatter, but NO uuid
    _w(tmp_path / "x" / "A.md", "[B](../y/B.md)\n")
    a = tmp_path / "x" / "A.md"
    b = tmp_path / "y" / "B.md"

    # dry-run: the out-of-scope write is announced before it happens (FR-006)
    dry = plan_robustify(tmp_path, only={a.resolve()})
    assert any(f.kind is Kind.TARGET_UUID_WRITE and f.file.resolve() == b.resolve()
               for f in dry.findings)

    # apply: the uuid lands in B (the one write allowed outside --only) and A is anchored to it
    main([str(tmp_path), "--robustify", "--write", "--only", str(a)])
    u = read_uuid_from_content(b.read_text())
    assert u is not None
    assert find_robust_links(a.read_text())[0].uuid == u


def test_no_target_writes_refuses_and_leaves_link_plain(tmp_path):
    _w(tmp_path / "y" / "B.md", "---\ntitle: B\n---\n# B\n")  # no uuid
    _w(tmp_path / "x" / "A.md", "[B](../y/B.md)\n")
    a = tmp_path / "x" / "A.md"
    b = tmp_path / "y" / "B.md"
    before = _tree_hashes(tmp_path)

    rc = main([str(tmp_path), "--robustify", "--write", "--only", str(a), "--no-target-writes"])
    assert rc == 0
    assert _tree_hashes(tmp_path) == before                # NOTHING changed — the hard guarantee
    result = plan_robustify(tmp_path, only={a.resolve()}, allow_target_writes=False)
    assert any(f.kind is Kind.TARGET_WRITE_REFUSED for f in result.findings)
    assert read_uuid_from_content(b.read_text()) is None   # B never got a uuid


def test_no_target_writes_without_only_is_a_usage_error(tmp_path):
    _w(tmp_path / "A.md", "hi\n")
    assert main([str(tmp_path), "--robustify", "--no-target-writes"]) == 1


# --- 5. repair, narrowed -------------------------------------------------------------------------

def test_repair_under_only_fixes_outbound(tmp_path, capsys):
    _w(tmp_path / "new" / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", f"[B](old/B.md) <!-- uuid: {U} -->\n")   # stale path — B moved to new/
    a = tmp_path / "A.md"
    rc = main([str(tmp_path), "--write", "--only", str(a)])
    assert rc == 0
    assert find_robust_links(a.read_text())[0].href.endswith("new/B.md")
    out = capsys.readouterr().out
    assert "inbound" in out.lower()                         # FR-008: warns it did not see inbound links


def test_repair_under_only_does_not_touch_inbound_in_other_files(tmp_path):
    # C points at A by uuid; A moves. A scoped repair on A must NOT fix C (that is a full-tree job).
    _w(tmp_path / "moved" / "A.md", f"---\nuuid: {V}\n---\n# A\n")
    _w(tmp_path / "C.md", f"[A](A.md) <!-- uuid: {V} -->\n")       # stale: A now under moved/
    before = (tmp_path / "C.md").read_text()
    main([str(tmp_path), "--write", "--only", str(tmp_path / "moved" / "A.md")])
    assert (tmp_path / "C.md").read_text() == before               # inbound untouched


# --- 6. guard rails ------------------------------------------------------------------------------

def test_only_nonexistent_path_errors(tmp_path):
    _w(tmp_path / "A.md", "hi\n")
    assert main([str(tmp_path), "--robustify", "--only", str(tmp_path / "nope.md")]) == 1


def test_only_non_md_path_errors(tmp_path):
    _w(tmp_path / "A.md", "hi\n")
    _w(tmp_path / "note.txt", "x\n")
    assert main([str(tmp_path), "--robustify", "--only", str(tmp_path / "note.txt")]) == 1


def test_only_outside_root_errors(tmp_path):
    root = tmp_path / "repo"
    _w(root / "A.md", "hi\n")
    outside = tmp_path / "elsewhere.md"
    _w(outside, "---\nuuid: x\n---\n")
    assert main([str(root), "--robustify", "--only", str(outside)]) == 1


def test_resolve_write_scope_unit(tmp_path):
    _w(tmp_path / "A.md", "hi\n")
    assert resolve_write_scope([], tmp_path) is None                # no narrowing
    scope = resolve_write_scope([str(tmp_path / "A.md")], tmp_path)
    assert scope == {(tmp_path / "A.md").resolve()}
    with pytest.raises(ScopeError):
        resolve_write_scope([str(tmp_path / "ghost.md")], tmp_path)


# --- 7. piped list (--only-from -) ---------------------------------------------------------------

def test_only_from_stdin_matches_repeated_only(tmp_path, monkeypatch):
    import io
    _w(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", "[B](B.md)\n")
    a = tmp_path / "A.md"
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{a}\n"))
    rc = main([str(tmp_path), "--robustify", "--write", "--only-from", "-"])
    assert rc == 0
    assert find_robust_links(a.read_text())[0].uuid == U


# --- 8. regression: no --only is byte-identical; a file positional still errors -------------------

def test_no_only_is_unchanged_behaviour(tmp_path):
    _w(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "A.md", "[B](B.md)\n")
    plain = plan_robustify(tmp_path)
    scoped_none = plan_robustify(tmp_path, only=None)
    assert plain.new_content.keys() == scoped_none.new_content.keys()
    assert plain.suppressed == 0


def test_positional_file_still_errors(tmp_path):
    f = tmp_path / "A.md"
    _w(f, "hi\n")
    assert main([str(f), "--robustify"]) == 2               # "not a directory" — unchanged contract


# --- check --only (FR-010) -----------------------------------------------------------------------

def test_check_only_limits_findings_to_scoped_source(tmp_path):
    _w(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "mine.md", "[B](B.md)\n")                 # anchorable plain link — mine
    _w(tmp_path / "theirs.md", "[B](B.md)\n")               # anchorable plain link — someone else's
    # scoped to mine.md: strict failure is only about my file
    assert main(["check", str(tmp_path), "--only", str(tmp_path / "mine.md")]) == 3
    # scoped to a clean file: green, despite theirs.md being dirty
    _w(tmp_path / "clean.md", f"[B](B.md) <!-- uuid: {U} -->\n")
    assert main(["check", str(tmp_path), "--only", str(tmp_path / "clean.md")]) == 0


def test_check_only_ignores_others_invalid_frontmatter(tmp_path):
    # someone else's invalid YAML must not fail my scoped check (no deadlock)
    _w(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _w(tmp_path / "theirs.md", "---\n: : bad yaml\n---\n# broken\n")
    _w(tmp_path / "mine.md", f"[B](B.md) <!-- uuid: {U} -->\n")   # clean
    assert main(["check", str(tmp_path), "--only", str(tmp_path / "mine.md")]) == 0
