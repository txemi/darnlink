"""Path helpers: split fragments and compute a link path relative to the linking file."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple


def split_fragment(href: str) -> Tuple[str, str]:
    """Split `path#frag` into (`path`, `frag`); frag is '' if none."""
    if "#" in href:
        path, frag = href.split("#", 1)
        return path, frag
    return href, ""


def resolve_href(href: str, linking_file: Path) -> Path:
    """Absolute path the href points to, resolved relative to the linking file's directory.

    The fragment is dropped. Returns a resolved (normalized) path; the target need not exist.
    """
    path_part, _ = split_fragment(href)
    return (linking_file.parent / path_part).resolve()


def relative_link(target: Path, linking_file: Path, fragment: str = "") -> str:
    """Path to `target` written relative to the directory of `linking_file`, POSIX style.

    Re-appends `#fragment` if given. This is the value to write inside `(...)`.
    """
    rel = os.path.relpath(target.resolve(), start=linking_file.parent.resolve())
    rel_posix = Path(rel).as_posix()
    return f"{rel_posix}#{fragment}" if fragment else rel_posix


def is_local_md(href: str) -> bool:
    """True if href is a relative link to a local .md file (not a URL, not an anchor-only link)."""
    path_part, _ = split_fragment(href)
    if not path_part:
        return False  # bare #fragment
    low = path_part.lower()
    if "://" in low or low.startswith(("http:", "https:", "mailto:", "ftp:", "/")):
        return False
    return low.endswith(".md")
