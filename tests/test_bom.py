"""A leading UTF-8 BOM (common on Windows-authored files) must not hide the frontmatter.
darnlink reads with utf-8-sig, so the BOM is stripped on read and `---` is seen normally."""
from pathlib import Path

from darnlink.links import find_robust_links
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
