"""Build a `uuid -> file` index by scanning Markdown frontmatter.

This plain dictionary replaces the predecessor's heavy entity model
(`csv_data_manager`/`MarkdownRepoIndex`) — it is the core of the L1 split.
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import frontmatter

DEFAULT_EXCLUDES = {".git", "node_modules", ".venv", "__pycache__", "_build", ".tox", "dist", "build"}


def dir_excluded(name: str, excludes) -> bool:
    """A directory name is excluded if it matches any pattern by glob (fnmatch, case-sensitive).
    A pattern with no wildcards matches exactly, so plain names (`node_modules`) still work — the
    glob is purely additive. Lets a repo exclude a family with one line, e.g. `old`, `old_*`, `*_old`."""
    return any(fnmatch.fnmatchcase(name, pat) for pat in excludes)


@dataclass
class FrontmatterIndex:
    by_uuid: Dict[str, Path] = field(default_factory=dict)
    duplicates: Dict[str, List[Path]] = field(default_factory=dict)
    invalid: List[Path] = field(default_factory=list)  # files whose frontmatter is not valid YAML
    out_of_root: List[Path] = field(default_factory=list)  # symlinks skipped because their target lives outside the scanned root

    def get(self, uuid: str) -> Path | None:
        return self.by_uuid.get(uuid.lower())

    def is_ambiguous(self, uuid: str) -> bool:
        return uuid.lower() in self.duplicates


def iter_markdown_files(
    root: Path,
    excludes: set[str] = DEFAULT_EXCLUDES,
    out_of_root: List[Path] | None = None,
) -> Iterator[Path]:
    """Yield all `.md` files under `root`, skipping excluded directory names.

    Each underlying file is yielded ONCE, under its canonical path. A symlink whose target is
    already indexed is skipped: it is another NAME for the same file, not another file.

    Why this matters. Sharing one instruction file across agents is standard practice —
    `AGENTS.md`, `.github/copilot-instructions.md` and `CLAUDE.md` as links to a single source, so
    no copy can drift. Without this dedup, that layout makes the same `uuid` appear at three paths
    and the integrity check fails with "uuid in multiple files": a FALSE positive, since a symlink
    creates no new entity, only a new name. Measured 2026-08-16 on a real repo — the gate went red
    and blocked every push until the links were reverted.

    Two more things it fixes, both consequences of treating a link as its own file: relative links
    in the body were resolved from the LINK's directory (a body link `inventory/notes/` read from
    `.github/` looked broken and repair wanted to rewrite it), and a write operation on the link
    would have gone THROUGH it into the shared source.

    A symlink pointing OUTSIDE `root` is skipped: the scan is defined by the root it was given, and
    following a link out of it would index files the caller never asked for.

    ⚠️ Skipping it is NOT free, and the caller must be told. Before this change such a file WAS
    indexed (reading a symlink follows it transparently), so its uuid resolved; after it, a robust
    link pointing at that uuid silently degrades to `unresolvable`. Silence is the failure mode this
    project exists to remove, so the skipped paths are collected in `out_of_root` and surfaced by
    the caller — the same treatment `invalid` frontmatter gets. Caught by an adversarial review of
    the very PR that introduced this: the first version claimed it "mirrors how out-of-root targets
    are reported" and did not report anything at all.
    """
    root = root.resolve()
    seen: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not dir_excluded(d, excludes)]
        for fn in filenames:
            if not fn.lower().endswith(".md"):
                continue
            path = Path(dirpath) / fn
            try:
                real = path.resolve(strict=True)
            except OSError:
                # Broken symlink (or unreadable): not a file to index. It is still a valid link
                # TARGET for other documents, so it is skipped quietly rather than failing here —
                # a dangling target is the dangling gate's job to report, not the indexer's.
                continue
            if real in seen:
                continue
            if not real.is_relative_to(root):
                if out_of_root is not None:
                    out_of_root.append(path)
                continue
            seen.add(real)
            # The CANONICAL path is yielded, never the link's own path, and the difference is not
            # cosmetic: relative links in the body are resolved against the directory of the file
            # they were read from. Reporting `.github/copilot-instructions.md` would resolve a body
            # link `inventory/notes/` from `.github/` and call it broken. `os.walk` order would
            # otherwise decide which name wins (`AGENTS.md` sorts before `CLAUDE.md`).
            yield real


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


def scan_tree(
    root: Path, excludes: set[str] = DEFAULT_EXCLUDES
) -> Tuple[List[Path], Dict[Path, str], List[Path]]:
    """ONE walk of `root`, reading every `.md` file exactly once: `(files, contents, out_of_root)`.

    #87: `build_index` and `plan_repairs`/`plan_robustify` each used to call `iter_markdown_files`
    and re-read every file independently — the SAME ~3.500 files, from disk, twice per `check`
    invocation (`check` runs the integrity axis via an index, then the strict axis via robustify).
    Measured on a large repo in the fleet: ~25-30s per pass, so a plain `check` paid for two full
    tree reads to produce two verdicts neither of which alone needed the other's walk to also happen.

    This is the ONE walk both axes now share. `read_text_keep_newlines` (byte-preserving: CRLF and
    a leading BOM survive verbatim) is used rather than `read_text()`'s universal-newline read that
    `build_index` used before this — parsing YAML frontmatter for a `uuid` does not care about the
    line-ending style, so this is a safe unification, not a behaviour change for the index; it is
    the mode the WRITE-side callers (repair, robustify) always needed, so unifying on it (rather
    than on the other reader) is what makes sharing one read serve both.
    """
    files: List[Path] = []
    contents: Dict[Path, str] = {}
    out_of_root: List[Path] = []
    for path in iter_markdown_files(root, excludes, out_of_root=out_of_root):
        try:
            from .frontmatter_edit import read_text_keep_newlines  # local: avoid a module cycle
            content = read_text_keep_newlines(path)
        except Exception:
            continue
        files.append(path)
        contents[path] = content
    return files, contents, out_of_root


def index_from_contents(
    files: List[Path], contents: Dict[Path, str], out_of_root: List[Path]
) -> FrontmatterIndex:
    """Build a `FrontmatterIndex` from an already-read scan (see `scan_tree`) — no disk I/O.

    Split from `build_index` so a caller that already scanned the tree for another reason (`check`,
    which also needs `plan_repairs`/`plan_robustify`'s view of the same files) can reuse that scan
    instead of triggering a second one. `build_index` itself is unchanged for every other caller —
    it still does its own scan and calls straight through to this.
    """
    from .links import file_is_ignored  # local import: links has no package deps, but keep it lazy

    index = FrontmatterIndex()
    index.out_of_root.extend(out_of_root)
    for path in files:
        content = contents[path]
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


def build_index(root: Path, excludes: set[str] = DEFAULT_EXCLUDES) -> FrontmatterIndex:
    """Scan `root` and map each frontmatter `uuid` to its file. Records duplicates separately.

    Files carrying the `<!-- darnlink-ignore-file -->` marker are skipped: an opted-out file is not
    a resolvable target, so a robust link pointing at its uuid is reported unresolvable (FR-019).

    Does its OWN scan — this is the entry point for every caller that only needs the index (`repair`
    CLI's target resolution, tests, external consumers). A caller that ALSO needs `plan_repairs`
    and/or `plan_robustify` on the SAME tree should call `scan_tree` once and pass the result to all
    three, via `index_from_contents` for this half — see `_run_check` in `cli.py`.
    """
    files, contents, out_of_root = scan_tree(root, excludes)
    return index_from_contents(files, contents, out_of_root)
