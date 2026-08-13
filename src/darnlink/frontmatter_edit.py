"""Surgical frontmatter edits: read/insert a `uuid` without reformatting the rest of the file.

We deliberately avoid re-dumping YAML (which would reorder keys and create noisy diffs and risks
the truncation bug seen in the predecessor). Instead we textually insert a `uuid:` line.
"""
from __future__ import annotations

import re
import uuid as _uuid
from typing import Optional, Tuple

# A leading YAML frontmatter block: ---\n <body> \n---\n <rest>
_FM_BLOCK_RE = re.compile(r"\A(---\s*\n)(.*?\n?)(---\s*\n)(.*)\Z", re.DOTALL)
_UUID_LINE_RE = re.compile(r"^uuid:\s*(.+)$", re.MULTILINE)


def new_uuid() -> str:
    return str(_uuid.uuid4())


def detect_newline(content: str) -> str:
    r"""The file's dominant line ending: '\r\n' if any CRLF is present, else '\n'."""
    return "\r\n" if "\r\n" in content else "\n"


def read_text_keep_newlines(path) -> str:
    """Read text WITHOUT universal-newline translation, so CRLF/LF are preserved verbatim.

    Uses utf-8-sig so a leading UTF-8 BOM (common on Windows-authored files) is stripped on read —
    otherwise it would sit before the `---` and break frontmatter detection. Files with no BOM are
    read identically to plain utf-8.
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        return f.read()


def write_text_keep_newlines(path, content: str) -> None:
    r"""Write text verbatim — do NOT translate '\n' to the platform's os.linesep, and keep the BOM.

    The read side uses `utf-8-sig`, which *consumes* a leading BOM so it cannot sit before the `---`
    and break frontmatter detection. That is right, but it means the BOM is absent from the string
    handed back — and writing that string as plain utf-8 silently deleted it from the file.

    The BOM is recovered from the file **on disk** rather than threaded through every caller: this
    function already knows the path, and the flag would have to cross four write paths to arrive at
    the same answer. A file that does not exist yet (`--create-readme`, `--create-frontmatter`) has
    no BOM to preserve, which is also correct.

    Worth the three lines because this module's whole contract is byte preservation — it goes to
    real trouble to keep CRLF exactly — and dropping the BOM contradicted that on all four write
    paths at once. The CI matrix exists for *"Windows-authored files (BOM, CRLF, path separators)"*
    and could not see it: its BOM fixtures only ever covered files that are **read**. #68.
    """
    with open(path, "w", encoding=_encoding_preserving_bom(path), newline="") as f:
        f.write(content)


def _encoding_preserving_bom(path) -> str:
    """`utf-8-sig` if the file on disk already starts with a BOM, else plain `utf-8`."""
    try:
        with open(path, "rb") as f:
            return "utf-8-sig" if f.read(3) == b"\xef\xbb\xbf" else "utf-8"
    except OSError:
        return "utf-8"          # a file that does not exist yet has no BOM to keep


def read_uuid_from_content(content: str) -> Optional[str]:
    """Return the lowercased `uuid` from a leading frontmatter block, or None."""
    m = _FM_BLOCK_RE.match(content)
    if not m:
        return None
    um = _UUID_LINE_RE.search(m.group(2))
    if not um:
        return None
    return um.group(1).strip().strip("'\"").lower() or None


def has_frontmatter(content: str) -> bool:
    return _FM_BLOCK_RE.match(content) is not None


def add_uuid_to_content(
    content: str, uuid_value: str, create_frontmatter: bool
) -> Optional[str]:
    """Return content with `uuid: <uuid_value>` inserted into the frontmatter.

    - If a frontmatter block exists, insert the line just after the opening `---`.
    - If none exists, create a minimal block only when `create_frontmatter` is True.
    - Returns None when there is no frontmatter and creation is not allowed (caller skips).
    Assumes the file does not already have a uuid (caller checks).
    """
    nl = detect_newline(content)
    m = _FM_BLOCK_RE.match(content)
    if m:
        head, body, sep, rest = m.groups()
        return f"{head}uuid: {uuid_value}{nl}{body}{sep}{rest}"
    if create_frontmatter:
        return f"---{nl}uuid: {uuid_value}{nl}---{nl}{nl}{content}"
    return None
