"""darnlink must preserve a file's original line endings (CRLF/LF), not normalize them to the
platform's. Otherwise a `--write` on a CRLF repo (or a LF repo on Windows) rewrites every line."""
from pathlib import Path

from darnlink.robustify import plan_robustify, apply_robustify

U = "11111111-2222-3333-4444-555555555555"


def _wb(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))  # exact bytes — we control the newlines


def _only_crlf(raw: bytes) -> bool:
    return b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


def test_robustify_preserves_crlf_in_source(tmp_path):
    _wb(tmp_path / "B.md", f"---\r\nuuid: {U}\r\n---\r\n# B\r\n")
    _wb(tmp_path / "A.md", "line1\r\nSee [B](B.md) plain.\r\nline3\r\n")
    apply_robustify(plan_robustify(tmp_path))
    raw = (tmp_path / "A.md").read_bytes()
    assert b"<!-- uuid:" in raw          # the link was robustified
    assert _only_crlf(raw)               # ...and CRLF was preserved (no bare LF introduced)


def test_created_frontmatter_uses_file_newline(tmp_path):
    _wb(tmp_path / "B.md", "no frontmatter here\r\nbody\r\n")  # CRLF target, no frontmatter
    _wb(tmp_path / "A.md", "[B](B.md)\r\n")
    apply_robustify(plan_robustify(tmp_path, create_frontmatter=True))
    raw_b = (tmp_path / "B.md").read_bytes()
    assert raw_b.startswith(b"---\r\nuuid:")  # created frontmatter matches the file's CRLF
    assert _only_crlf(raw_b)


def test_lf_stays_lf(tmp_path):
    _wb(tmp_path / "B.md", f"---\nuuid: {U}\n---\n# B\n")
    _wb(tmp_path / "A.md", "[B](B.md)\n")
    apply_robustify(plan_robustify(tmp_path))
    raw = (tmp_path / "A.md").read_bytes()
    assert b"\r\n" not in raw             # pure-LF file stays pure LF
