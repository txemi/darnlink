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
from typing import Dict, List

from .frontmatter_index import DEFAULT_EXCLUDES, FrontmatterIndex, iter_markdown_files
from .links import (code_spans, emit_robust_link, file_ignores_links, file_is_ignored,
                    find_robust_links, ignored_spans)
from .paths import is_web_href, relative_link, resolve_href, split_fragment
from .frontmatter_edit import read_text_keep_newlines, write_text_keep_newlines
from .report import Finding, Kind


@dataclass
class RepairResult:
    findings: List[Finding] = field(default_factory=list)
    new_content: Dict[Path, str] = field(default_factory=dict)  # files that would change
    ignored: List[Path] = field(default_factory=list)  # files skipped via the ignore-file marker
    link_ignored: List[Path] = field(default_factory=list)  # sources via the ignore-links marker (006)


def plan_repairs(
    root: Path,
    index: FrontmatterIndex,
    excludes: set = DEFAULT_EXCLUDES,
    block_markers: tuple = (),
) -> RepairResult:
    """Compute repairs for every robust link under `root` (no writes)."""
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
        if file_ignores_links(content):
            result.link_ignored.append(f)
            result.findings.append(Finding(
                Kind.IGNORED_LINKS, f,
                "file carries darnlink-ignore-links; its links are left as-is (still a target)"))
            continue
        ignore = ignored_spans(content, block_markers) + code_spans(content)
        links = find_robust_links(content, ignore)
        if not links:
            continue
        # rebuild content applying edits left-to-right; collect findings
        pieces: List[str] = []
        cursor = 0
        changed = False
        for link in links:
            # Feature 010: a robust link whose href is a web URL is a CROSS-REPO link; its uuid may
            # live in another repository the core never scans. The core stays local (P-III/P-IV) and
            # leaves it alone — `darnlink web-check` handles it. Without this guard the core wrongly
            # reports it `unresolvable`, which would fail an existing gate the moment a web link appears.
            if is_web_href(link.href):
                continue
            if index.is_ambiguous(link.uuid):
                result.findings.append(
                    Finding(Kind.AMBIGUOUS, f, f"uuid {link.uuid} in multiple files; left untouched")
                )
                continue
            target = index.get(link.uuid)
            if target is None:
                result.findings.append(
                    Finding(Kind.UNRESOLVABLE, f, f"uuid {link.uuid} not found; left untouched")
                )
                continue
            current = resolve_href(link.href, f)
            if current == target.resolve():
                continue  # already correct (cosmetic ./ differences are fine)
            if current.is_file():
                # The written path still points to a real file, but the uuid lives elsewhere:
                # the two halves of the robust link disagree (typically a mis-pasted uuid). This
                # is NOT a moved target, so don't guess which side is right — flag it for review.
                result.findings.append(
                    Finding(
                        Kind.CONFLICT,
                        f,
                        f"{link.href} resolves to an existing file, but uuid {link.uuid} lives in "
                        f"{target} — path and uuid disagree; left untouched",
                    )
                )
                continue
            _, frag = split_fragment(link.href)
            new_href = relative_link(target, f, frag)
            result.findings.append(Finding(Kind.REPAIR, f, f"{link.href} -> {new_href}"))
            # splice the rewritten robust link in place of the old span
            pieces.append(content[cursor:link.start])
            pieces.append(emit_robust_link(link.text, new_href, link.uuid))
            cursor = link.end
            changed = True
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
