"""Build a `uuid -> file` index by scanning Markdown frontmatter.

This plain dictionary replaces the predecessor's heavy entity model
(`csv_data_manager`/`MarkdownRepoIndex`) — it is the core of the L1 split.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List

import frontmatter

DEFAULT_EXCLUDES = {".git", "node_modules", ".venv", "__pycache__", "_build", ".tox", "dist", "build"}


@dataclass
class FrontmatterIndex:
    by_uuid: Dict[str, Path] = field(default_factory=dict)
    duplicates: Dict[str, List[Path]] = field(default_factory=dict)
    invalid: List[Path] = field(default_factory=list)  # files whose frontmatter is not valid YAML

    def get(self, uuid: str) -> Path | None:
        return self.by_uuid.get(uuid.lower())

    def is_ambiguous(self, uuid: str) -> bool:
        return uuid.lower() in self.duplicates


def iter_markdown_files(root: Path, excludes: set[str] = DEFAULT_EXCLUDES) -> Iterator[Path]:
    """Yield all `.md` files under `root`, skipping excluded directory names."""
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in excludes]
        for fn in filenames:
            if fn.lower().endswith(".md"):
                yield Path(dirpath) / fn


def read_frontmatter_uuid(content: str) -> tuple[str, str | None]:
    """Canonical uuid reader, used by EVERY operation (index, repair, robustify).

    Returns `(status, uuid)`:
      - `("none", None)`    no leading frontmatter block at all.
      - `("invalid", None)` a frontmatter block that is NOT valid YAML — reported, never read/written.
      - `("valid", uuid)`   well-formed YAML; `uuid` is the lowercased value or None if absent.

    Parsing is delegated to `python-frontmatter` (PyYAML) — the standard for the format (FORMAT.md).
    A tolerant regex MUST NOT be used here: it would accept what YAML rejects (FR-023/FR-024)."""
    from .frontmatter_edit import has_frontmatter  # regex presence-check; no cycle (links-free module)

    if not has_frontmatter(content):
        return ("none", None)
    try:
        meta = frontmatter.loads(content).metadata
    except Exception:
        return ("invalid", None)
    if not isinstance(meta, dict):
        return ("invalid", None)
    u = meta.get("uuid")
    if u is None:
        return ("valid", None)
    if not isinstance(u, str):
        return ("invalid", None)  # uuid present but not a string scalar (list/dict/number): malformed
    return ("valid", u.strip().lower() or None)


def build_index(root: Path, excludes: set[str] = DEFAULT_EXCLUDES) -> FrontmatterIndex:
    """Scan `root` and map each frontmatter `uuid` to its file. Records duplicates separately.

    Files carrying the `<!-- darnlink-ignore-file -->` marker are skipped: an opted-out file is not
    a resolvable target, so a robust link pointing at its uuid is reported unresolvable (FR-019)."""
    from .links import file_is_ignored  # local import: links has no package deps, but keep it lazy

    index = FrontmatterIndex()
    for path in iter_markdown_files(root, excludes):
        try:
            content = path.read_text(encoding="utf-8")  # read once: marker + uuid both come from it
        except Exception:
            continue
        if file_is_ignored(content):
            continue
        status, u = read_frontmatter_uuid(content)
        if status == "invalid":
            index.invalid.append(path)  # report; an invalid file is never a resolvable target (FR-024)
            continue
        if not u:
            continue
        if u in index.duplicates:
            index.duplicates[u].append(path)
        elif u in index.by_uuid:
            # second sighting: promote to duplicate, drop from the unambiguous map
            first = index.by_uuid.pop(u)
            index.duplicates[u] = [first, path]
        else:
            index.by_uuid[u] = path
    return index
