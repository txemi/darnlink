"""Repair: rewrite a robust link's path to wherever its UUID now lives.

A robust link is *broken* when its written path does not resolve to the file whose frontmatter
`uuid` matches the link's uuid. We then rewrite the path (relative to the linking file),
preserving the link text, any `#fragment`, and the uuid comment. Exact-uuid match only; no guessing.

Defensive rule: we only auto-repair when the written path is *stale* — i.e. it does not resolve
to an existing file. If the path STILL resolves to a real (different) file while the uuid lives
elsewhere, the two halves of the link disagree (typically a mis-pasted uuid). That is a CONFLICT,
not a move: we leave it untouched and report it for a human to resolve, rather than silently
following the uuid and hijacking a link whose path was the real intent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from .frontmatter_index import DEFAULT_EXCLUDES, FrontmatterIndex, iter_markdown_files
from .links import (code_spans, emit_robust_link, file_ignores_links, file_is_ignored,
                    find_robust_links, ignored_spans)
from .paths import DIR_ANCHOR, names_md, relative_link, resolve_href, split_fragment
from .frontmatter_edit import read_text_keep_newlines, write_text_keep_newlines
from .report import Finding, Kind
from .scope import in_scope


@dataclass
class RepairResult:
    findings: List[Finding] = field(default_factory=list)
    new_content: Dict[Path, str] = field(default_factory=dict)  # files that would change
    ignored: List[Path] = field(default_factory=list)  # files skipped via the ignore-file marker
    link_ignored: List[Path] = field(default_factory=list)  # sources via the ignore-links marker (006)
    suppressed: int = 0  # findings in files outside the write scope (feature 010): counted, never hidden


def plan_repairs(
    root: Path,
    index: FrontmatterIndex,
    excludes: set = DEFAULT_EXCLUDES,
    block_markers: tuple = (),
    only: Optional[Set[Path]] = None,
) -> RepairResult:
    """Compute repairs for every robust link under `root` (no writes).

    `only` (feature 010) narrows the **write** scope: files outside it are still scanned and still
    resolve as targets — the index is built from the whole tree — but their own links are neither
    rewritten nor reported as actionable; they are counted in `suppressed`. A narrowed run therefore
    sees only **outbound** links of the scoped files: a moved target's *inbound* links live in files
    the caller did not name, and still need a full-tree run.
    """
    result = RepairResult()
    for f in iter_markdown_files(root, excludes):
        try:
            content = read_text_keep_newlines(f)
        except Exception:
            continue
        if file_is_ignored(content):
            result.ignored.append(f)
            continue
        # Feature 006: its links are never rewritten — not even to fix a stale path. The generator
        # re-emits the correct path on its next run; darnlink must not fight it. Unlike ignore-file
        # this does NOT touch the target axis: the index still resolves this file's uuid (FR-034).
        scoped = in_scope(f, only)  # feature 010: may this file be written / reported on?
        if file_ignores_links(content):
            result.link_ignored.append(f)
            if scoped:
                result.findings.append(Finding(
                    Kind.IGNORED_LINKS, f,
                    "file carries darnlink-ignore-links; its links are left as-is (still a target)"))
            continue
        ignore = ignored_spans(content, block_markers) + code_spans(content)
        links = find_robust_links(content, ignore)
        if not links:
            continue
        # rebuild content applying edits left-to-right; collect findings
        local: List[Finding] = []  # this file's findings; kept only if it is in the write scope
        pieces: List[str] = []
        cursor = 0
        changed = False
        for link in links:
            if index.is_ambiguous(link.uuid):
                local.append(
                    Finding(Kind.AMBIGUOUS, f, f"uuid {link.uuid} in multiple files; left untouched")
                )
                continue
            target = index.get(link.uuid)
            if target is None:
                local.append(
                    Finding(Kind.UNRESOLVABLE, f, f"uuid {link.uuid} not found; left untouched")
                )
                continue
            current = resolve_href(link.href, f)
            _, frag = split_fragment(link.href)
            # Feature 011: a link whose path does not name a `.md` file is a *directory* link — the
            # uuid identifies the directory via its README.md, and the link points at the directory
            # (the README's parent), not at the README file itself.
            dir_link = not names_md(link.href)
            if dir_link and target.name.lower() != DIR_ANCHOR.lower():
                # The path names a directory but the uuid lives in a non-README file: the two halves
                # disagree. Don't guess — flag like any other path/uuid conflict.
                local.append(
                    Finding(
                        Kind.CONFLICT,
                        f,
                        f"{link.href} is a directory link, but uuid {link.uuid} lives in {target} "
                        f"(not a {DIR_ANCHOR}) — path and uuid disagree; left untouched",
                    )
                )
                continue
            intended = target.parent if dir_link else target
            if current == intended.resolve():
                continue  # already correct (cosmetic ./ or trailing-slash differences are fine)
            # Defensive: the written path still resolves to a real target while the uuid lives
            # elsewhere — the two halves disagree (typically a mis-pasted uuid). It is NOT a move, so
            # flag, don't hijack. A file link keys on a real *file* (its existing behavior); a
            # directory link keys on the path resolving to *anything* — a real directory, or a file
            # that shadows the folder path — so a non-`.md` link whose path is still a live file is a
            # conflict, not a rewrite.
            if current.exists() if dir_link else current.is_file():
                kind_word = "file" if current.is_file() else "directory"
                local.append(
                    Finding(
                        Kind.CONFLICT,
                        f,
                        f"{link.href} resolves to an existing {kind_word}, but uuid {link.uuid} lives "
                        f"in {target} — path and uuid disagree; left untouched",
                    )
                )
                continue
            base = relative_link(intended, f)  # path only; fragment re-appended below
            if dir_link and not base.endswith("/"):
                base += "/"  # keep directory links visibly directories (and re-recognisable as such)
            new_href = f"{base}#{frag}" if frag else base
            local.append(Finding(Kind.REPAIR, f, f"{link.href} -> {new_href}"))
            # splice the rewritten robust link in place of the old span
            pieces.append(content[cursor:link.start])
            pieces.append(emit_robust_link(link.text, new_href, link.uuid))
            cursor = link.end
            changed = True
        if not scoped:
            # Outside the write scope: nothing is written and nothing is reported as actionable —
            # but the count is surfaced, so a narrowed run never reads as "the tree is clean".
            result.suppressed += len(local)
            continue
        result.findings.extend(local)
        if changed:
            pieces.append(content[cursor:])
            result.new_content[f] = "".join(pieces)
    return result


def apply_repairs(result: RepairResult) -> List[Path]:
    """Write the planned changes to disk. Returns the files written."""
    written: List[Path] = []
    for path, content in result.new_content.items():
        write_text_keep_newlines(path, content)
        written.append(path)
    return written
