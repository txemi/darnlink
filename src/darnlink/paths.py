"""Path helpers: split fragments and compute a link path relative to the linking file."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple


# Feature 011: a link to a directory is anchored to the uuid of this file inside it. A folder has no
# frontmatter of its own, so its README.md carries the folder's stable identity.
DIR_ANCHOR = "README.md"


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


def is_web_href(href: str) -> bool:
    """True if href is an absolute web URL (http/https). Feature 013: the core repair/check path must
    skip robust links whose href is a URL — their uuid may live in ANOTHER repo, which the core never
    scans, so treating them as local would wrongly report them `unresolvable`. Cross-repo web links are
    handled only by the opt-in `web-check` subcommand (specs/013-web-robustness)."""
    return href.strip().lower().startswith(("http://", "https://"))


def is_local_relative(href: str) -> bool:
    """True if href is a relative link into the local tree (not a URL, mailto, absolute or bare
    `#anchor`). Says nothing about what the path names — a `.md` file, a directory, anything."""
    path_part, _ = split_fragment(href)
    if not path_part:
        return False  # bare #fragment
    low = path_part.lower()
    if "://" in low or low.startswith(("http:", "https:", "mailto:", "ftp:", "/")):
        return False
    return True


def is_local_md(href: str) -> bool:
    """True if href is a relative link to a local .md file (not a URL, not an anchor-only link)."""
    path_part, _ = split_fragment(href)
    return is_local_relative(href) and path_part.lower().endswith(".md")


def is_absolute_local_path(href: str) -> bool:
    """True if href names an absolute filesystem path (`/home/user/x.md`), not a URL.

    `is_local_relative` excludes this shape (it starts with `/`), so it falls out of the scan
    silently: not dangling-checked (`_dangling_target` shares the same exclusion) and not
    `out_of_scope` (that axis names a target outside `--root`, which presumes a relative path
    resolved from the linking file — an absolute path names no root-relative location at all).
    A protocol-relative URL (`//example.com/x`) is excluded too; it is a scheme, not a path.
    """
    path_part, _ = split_fragment(href)
    return bool(path_part) and path_part.startswith("/") and not path_part.startswith("//")


def names_md(href: str) -> bool:
    """True if the href's path part names a `.md` file (by suffix). Used to tell a link that points
    at a file (`foo/README.md`) from one that points at a directory (`foo/`), independent of disk.

    Strips surrounding whitespace before checking the suffix (FR-066). A trailing space is never
    part of what a link destination *means* -- CommonMark does not count it as content -- but before
    this it made `"old/B.md ".endswith(".md")` false, so `repair` misread a plain file link as a
    *directory* link. The uuid it carries then lives in a non-README file, which reads as "path and
    uuid disagree" and is reported as an unhealable CONFLICT -- a false, permanent diagnosis of a
    link that was actually fine. This is the ONLY strip in the resolution path: `resolve_href` still
    uses the href verbatim, so a link whose destination genuinely differs only by that space still
    fails to resolve to the real file and gets corrected by the normal repair-a-stale-link path, not
    silently treated as already-correct.

    ⚠️ `robustify._anchor_target` and `_dir_link_missing_readme` have the SAME "type says file/dir,
    raw resolution finds nothing" combination for a plain (not-yet-anchored) link -- confirmed by
    reproduction, not fixed here. #67's own body names both sites explicitly and defers them to #74,
    which is still open: a prior attempt at exactly this kind of edge-strip (nine review rounds, #62)
    shipped a "121/121 vs cmark" formulation that still regressed two real files in the fleet, because
    it reasoned about the destination's *edges* and never measured its *interior* against a real
    corpus. `tests/test_dangling_links.py::test_whitespace_around_a_destination_is_NOT_stripped_here`
    pins the current (unstripped) behaviour on the sibling `dangling` axis for exactly this reason --
    do not widen the strip here to those two call sites without going through #74.
    """
    path_part, _ = split_fragment(href)
    return path_part.strip().lower().endswith(".md")
