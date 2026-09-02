from pathlib import Path

from darnlink import cli, paths
from darnlink.paths import (relative_link, resolve_cache, resolve_href, resolved,
                            split_fragment, is_local_md)


def test_split_fragment():
    assert split_fragment("a/b.md#sec") == ("a/b.md", "sec")
    assert split_fragment("a/b.md") == ("a/b.md", "")


def test_relative_link_across_dirs(tmp_path):
    a = tmp_path / "A.md"
    target = tmp_path / "new" / "B.md"
    assert relative_link(target, a) == "new/B.md"
    # from a nested linking file, path climbs up correctly
    nested = tmp_path / "deep" / "x" / "C.md"
    assert relative_link(target, nested) == "../../new/B.md"


def test_relative_link_preserves_fragment(tmp_path):
    a = tmp_path / "A.md"
    target = tmp_path / "new" / "B.md"
    assert relative_link(target, a, "sec") == "new/B.md#sec"


def test_resolve_href_drops_fragment(tmp_path):
    a = tmp_path / "sub" / "A.md"
    a.parent.mkdir(parents=True)
    assert resolve_href("../new/B.md#sec", a) == (tmp_path / "new" / "B.md").resolve()


def test_is_local_md():
    assert is_local_md("a/b.md")
    assert is_local_md("b.md#sec")
    assert not is_local_md("https://example.com/x.md")
    assert not is_local_md("#anchor")
    assert not is_local_md("img.png")


# --- Resolution cache (perf: 81.7% of resolve() calls in a real run are repeats) ---
#
# Two halves are pinned here, and they are the whole design: inside a scope `resolved()` must be
# indistinguishable from `resolve()` except in speed, and OUTSIDE one it must not memoise at all --
# so the public plan_*/apply_* API can never hand an embedder a stale resolution.


def test_resolved_matches_resolve_inside_a_scope(tmp_path):
    with resolve_cache():
        real = tmp_path / "deep" / "x"
        real.mkdir(parents=True)
        for p in (real, tmp_path / "nope.md", tmp_path / ".." / tmp_path.name / "y.md"):
            assert resolved(p) == p.resolve()   # miss
            assert resolved(p) == p.resolve()   # hit returns the same thing


def test_resolved_follows_a_symlink_like_resolve(tmp_path):
    with resolve_cache():
        target = tmp_path / "real"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        assert resolved(link / "a.md") == (target / "a.md").resolve()


def _retarget(link, old, new):
    link.unlink()
    link.symlink_to(new, target_is_directory=True)


def test_no_scope_means_no_memoisation(tmp_path):
    """The safety that matters: an embedder calling the public API twice around a filesystem change
    gets the truth, not a cached answer. Without this, apply_robustify would write a WRONG uuid."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    link = tmp_path / "link"
    link.symlink_to(a, target_is_directory=True)
    assert resolved(link / "f.md") == (a / "f.md").resolve()
    _retarget(link, a, b)
    assert resolved(link / "f.md") == (b / "f.md").resolve()   # no scope -> never stale


def test_a_resolution_never_outlives_its_scope(tmp_path):
    """Inside one scope a retarget is deliberately invisible -- that is what buys the speed. Across
    two scopes it must not be: leaving the outermost scope drops every entry."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    link = tmp_path / "link"
    link.symlink_to(a, target_is_directory=True)
    with resolve_cache():
        assert resolved(link / "f.md") == (a / "f.md").resolve()
        _retarget(link, a, b)
        assert resolved(link / "f.md") == (a / "f.md").resolve()   # stale ON PURPOSE, same run
    with resolve_cache():
        assert resolved(link / "f.md") == (b / "f.md").resolve()   # new run -> truth again


def test_nesting_reuses_the_outer_scope_and_does_not_close_it_early(tmp_path):
    f = tmp_path / "f.md"
    with resolve_cache():
        with resolve_cache():
            first = resolved(f)
        assert paths._RESOLVE_CACHE is not None   # inner exit must NOT close the outer scope
        assert resolved(f) is first               # ...and the entry survives
    assert paths._RESOLVE_CACHE is None


def test_main_is_the_run_boundary(tmp_path):
    """`main()` opens the only scope in the shipped code path, and closing it is structural rather
    than a line someone can delete: there is no clear() to forget."""
    (tmp_path / "a.md").write_text("---\nuuid: 11111111-1111-4111-8111-111111111111\n---\n# a\n",
                                   encoding="utf-8")
    assert paths._RESOLVE_CACHE is None
    cli.main(["check", str(tmp_path)])
    assert paths._RESOLVE_CACHE is None           # the run ended -> nothing memoised survives it


def test_relative_paths_are_never_memoised(tmp_path, monkeypatch):
    """Their resolution depends on the cwd, which is not part of the key. darnlink never chdirs;
    an embedder might."""
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    with resolve_cache():
        monkeypatch.chdir(tmp_path / "one")
        first = resolved(Path("f.md"))
        monkeypatch.chdir(tmp_path / "two")
        assert resolved(Path("f.md")) != first
