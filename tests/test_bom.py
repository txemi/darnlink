"""A leading UTF-8 BOM (common on Windows-authored files) must not hide the frontmatter.
darnlink reads with utf-8-sig, so the BOM is stripped on read and `---` is seen normally."""
from pathlib import Path

from darnlink.frontmatter_index import build_index
from darnlink.links import find_robust_links
from darnlink.repair import plan_repairs, apply_repairs
from darnlink.robustify import plan_robustify, apply_robustify

U = "11111111-2222-3333-4444-555555555555"
BOM = b"\xef\xbb\xbf"


def test_bom_frontmatter_uuid_is_found(tmp_path):
    # Target file with a UTF-8 BOM before its frontmatter (as a Windows editor might write it).
    (tmp_path / "B.md").write_bytes(BOM + f"---\nuuid: {U}\ntitle: B\n---\n# B\n".encode("utf-8"))
    (tmp_path / "A.md").write_bytes(b"[B](B.md) plain\n")  # plain link to the BOM target

    apply_robustify(plan_robustify(tmp_path))

    # If the BOM hid the frontmatter, B's uuid wouldn't be found and the link wouldn't be
    # robustified (or would get a freshly invented uuid). With utf-8-sig it's read fine.
    links = find_robust_links((tmp_path / "A.md").read_text(encoding="utf-8-sig"))
    assert len(links) == 1
    assert links[0].uuid == U  # reused the BOM target's existing uuid


def test_bom_target_is_indexed_and_inbound_link_repairs(tmp_path):
    # Regression (caught on Windows): the INDEX path used plain utf-8, so a BOM sat before `---`
    # and hid the target's uuid — the index missed it and inbound robust links could not be
    # repaired. build_index must strip the BOM too (utf-8-sig), like robustify already did.
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "B.md").write_bytes(BOM + f"---\nuuid: {U}\n---\n# B\n".encode("utf-8"))
    (tmp_path / "A.md").write_text(f"[B](old/B.md) <!-- uuid: {U} -->\n", encoding="utf-8")

    # move B so A's path is now stale — repair must find B by its uuid
    (tmp_path / "new").mkdir()
    (tmp_path / "old" / "B.md").rename(tmp_path / "new" / "B.md")

    index = build_index(tmp_path)
    assert U in index.by_uuid  # the BOM must not hide the uuid from the index

    apply_repairs(plan_repairs(tmp_path, index))
    assert "(new/B.md)" in (tmp_path / "A.md").read_text()  # link repaired by uuid, not left stale
