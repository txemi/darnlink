"""A symlink is another NAME for a file, not another file.

Sharing one instruction file across agents (`AGENTS.md`, `.github/copilot-instructions.md` and
`CLAUDE.md` pointing at a single source) is standard practice. Before this behaviour, that layout
made the same uuid appear at several paths and the integrity check failed with "uuid in multiple
files" — a false positive that blocked every push on a real repo (2026-08-16).
"""
from pathlib import Path

from darnlink.frontmatter_index import build_index, iter_markdown_files

DOC = "---\nuuid: 11111111-2222-3333-4444-555555555555\n---\n\n# Source\n"


def _paths(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in iter_markdown_files(root)}


def test_symlink_to_indexed_file_is_not_a_second_file(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text(DOC, encoding="utf-8")
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")

    assert _paths(tmp_path) == {"CLAUDE.md"}


def test_symlink_does_not_make_the_uuid_ambiguous(tmp_path: Path) -> None:
    """The regression that motivated this: three names, one entity, no duplicate."""
    (tmp_path / "CLAUDE.md").write_text(DOC, encoding="utf-8")
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "copilot-instructions.md").symlink_to(Path("..") / "CLAUDE.md")

    index = build_index(tmp_path)

    assert index.duplicates == {}
    assert index.get("11111111-2222-3333-4444-555555555555") == (tmp_path / "CLAUDE.md").resolve()


def test_symlink_pointing_outside_the_root_is_skipped(tmp_path: Path) -> None:
    """The scan is defined by the root it was given; a link out of it does not widen the scan."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "other.md").write_text(DOC, encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.md").symlink_to(outside / "other.md")

    assert _paths(root) == set()


def test_a_skipped_out_of_root_symlink_is_REPORTED_not_silenced(tmp_path: Path) -> None:
    """The regression an adversarial review caught in this very change.

    Such a file used to be indexed (reading a symlink follows it), so its uuid resolved. Skipping
    it silently turns a working robust link into `unresolvable` with nothing naming the cause —
    the exact class of failure this project exists to remove.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "other.md").write_text(DOC, encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.md").symlink_to(outside / "other.md")

    index = build_index(root)

    assert index.get("11111111-2222-3333-4444-555555555555") is None, "not indexed, as designed"
    assert [p.name for p in index.out_of_root] == ["link.md"], "and the caller is told about it"


def test_broken_symlink_is_skipped_and_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / "real.md").write_text(DOC, encoding="utf-8")
    (tmp_path / "dangling.md").symlink_to("nope.md")

    assert _paths(tmp_path) == {"real.md"}


def test_the_canonical_path_wins_even_when_the_link_is_walked_first(tmp_path: Path) -> None:
    """Walk order must NOT decide which name is reported.

    `os.walk` yields in directory order, so a link can come before its target (`aaa.md` before
    `zzz.md`). Reporting the link would resolve the body's relative links from the LINK's
    directory — the bug this whole change exists to remove.
    """
    (tmp_path / "aaa.md").symlink_to("zzz.md")
    (tmp_path / "zzz.md").write_text(DOC, encoding="utf-8")

    assert _paths(tmp_path) == {"zzz.md"}


def test_a_link_in_a_subdir_does_not_shift_how_body_links_resolve(tmp_path: Path) -> None:
    """The concrete failure: a link under `.github/` made `inventory/notes/` look broken."""
    (tmp_path / "CLAUDE.md").write_text(DOC, encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "copilot-instructions.md").symlink_to(Path("..") / "CLAUDE.md")

    assert _paths(tmp_path) == {"CLAUDE.md"}


def test_every_cli_output_path_reports_it_not_just_the_human_one(tmp_path, capsys) -> None:
    """Round 2 of the review caught the first fix covering 1 of 6 output paths.

    `build_index` knowing about it internally is not the same as the user being told, and the path
    that matters most is the one nobody reads by eye: a gate consumes `--json`, and `check` is the
    subcommand documented for CI. Fixing only the human text would have moved the silence to where
    it does the most damage.
    """
    from darnlink.cli import main

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "other.md").write_text(DOC, encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.md").symlink_to(outside / "other.md")

    # ENUMERATED, not asserted to be "all": rounds 2 and 3 both failed on claiming completeness
    # without listing the surfaces. `web-check` is the one that got away twice.
    for argv in (
        [str(root)],
        [str(root), "--json"],
        [str(root), "--robustify"],
        [str(root), "--robustify", "--json"],
        ["check", str(root)],
        ["check", str(root), "--json"],
        ["web-check", str(root)],
        ["web-check", str(root), "--json"],
    ):
        main(argv)
        out = capsys.readouterr().out
        assert "out_of_root" in out or "out-of-root" in out, f"silent path: darnlink {' '.join(argv)}"


def test_write_never_touches_a_symlink_path_in_real_use(tmp_path):
    """D2: the invariant that makes writing through a symlink safe, PROVEN by driving the actual
    real-world layout end to end (AGENTS.md -> CLAUDE.md), not just read off the code.

    Every path that reaches `write_text_keep_newlines` comes from `iter_markdown_files`, directly
    or via an href resolved against a file that did -- and that function yields
    `Path.resolve(strict=True)`, which dereferences every symlink. So a write driven through the
    symlink NAME still lands on the canonical file, and never on the link itself.
    """
    import darnlink.robustify as rb  # the name as bound in THIS module -- patching
    from darnlink.frontmatter_edit import write_text_keep_newlines as orig
    from darnlink.robustify import apply_robustify, plan_robustify

    # `darnlink.frontmatter_edit.write_text_keep_newlines` here would not work: `robustify.py`
    # imported the function by name at module load, so it holds its own reference.

    seen: list[tuple[str, bool]] = []

    def spy(path, content):
        seen.append((str(path), Path(path).is_symlink()))
        return orig(path, content)

    rb.write_text_keep_newlines = spy
    try:
        (tmp_path / "CLAUDE.md").write_text("# Instrucciones\n", encoding="utf-8")
        (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")
        (tmp_path / "A.md").write_text("[ver](AGENTS.md)\n", encoding="utf-8")

        apply_robustify(plan_robustify(tmp_path, create_frontmatter=True))
    finally:
        rb.write_text_keep_newlines = orig

    assert seen, "the spy never fired -- the fixture stopped exercising a write at all"
    assert not any(is_link for _, is_link in seen), f"a symlink path reached the write site: {seen!r}"
    # And the write really did go through: CLAUDE.md (the canonical file) carries the new uuid,
    # readable through either name since they are the same inode.
    assert "uuid:" in (tmp_path / "CLAUDE.md").read_text()
    assert (tmp_path / "CLAUDE.md").read_text() == (tmp_path / "AGENTS.md").read_text()


def test_write_text_keep_newlines_refuses_a_symlink_path_directly(tmp_path):
    """The other half: prove the assertion actually FIRES, not just that real use never trips it.

    No caller in this codebase can reach `write_text_keep_newlines` with a symlink path today (the
    test above proves that for the one real layout this project cares about) -- so the only way to
    exercise the guard itself is to call the function directly with one, bypassing
    `iter_markdown_files` on purpose. That is exactly the scenario the guard exists for: some FUTURE
    caller that bypasses the resolution `iter_markdown_files` normally guarantees.
    """
    import pytest

    from darnlink.frontmatter_edit import write_text_keep_newlines

    (tmp_path / "CLAUDE.md").write_text("# Instrucciones\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")

    with pytest.raises(AssertionError, match="refusing to write through a symlink"):
        write_text_keep_newlines(tmp_path / "AGENTS.md", "new content\n")

    # And the guard did its job: nothing was touched through either name.
    assert (tmp_path / "CLAUDE.md").read_text() == "# Instrucciones\n"
