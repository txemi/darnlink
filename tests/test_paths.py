from pathlib import Path

from darnlink.paths import relative_link, resolve_href, split_fragment, is_local_md


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
