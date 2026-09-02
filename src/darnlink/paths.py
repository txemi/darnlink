"""Path helpers: split fragments and compute a link path relative to the linking file."""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple


# Feature 011: a link to a directory is anchored to the uuid of this file inside it. A folder has no
# frontmatter of its own, so its README.md carries the folder's stable identity.
DIR_ANCHOR = "README.md"


# --- Resolution cache -------------------------------------------------------
# `Path.resolve()` walks every component and issues real syscalls, and darnlink calls it on the
# SAME paths over and over: a run over a ~3,900-file tree issues 31,470 calls for only 5,767
# distinct paths - 81.7% of them repeats - and spends ~24% of the wall clock inside them.
#
# Memoising is sound for the duration of ONE run because a non-strict `resolve()` (= realpath) can
# only change if a symlink, a mount, or a directory-vs-symlink component changes. Creating a file,
# creating a `README.md` anchor, or rewriting file content cannot change it -- and content is the
# only thing darnlink ever writes (there is no mkdir/rename/symlink_to anywhere in `src/`).
#
# But "one run" is a concept only `main()` has: `plan_robustify`, `plan_repairs`, `resolve_write_scope`
# and friends are public, and an embedder calling them twice around a filesystem change would get a
# stale answer -- and, through `apply_robustify`, a WRONG uuid written to disk. So the cache is
# OPT-IN: `resolved()` is a plain passthrough unless a `resolve_cache()` scope is open, and `main()`
# opens exactly one. The worst that can happen to a library consumer is now that it is as slow as
# darnlink was before this cache existed, never that it is wrong.
#
# Relative paths are never memoised: their resolution depends on the process cwd. darnlink itself
# never chdirs, but `--only-from` accepts relative paths (its help advertises piping
# `git diff --cached --name-only`), so the key would be ambiguous for an embedder that does.
#
# The scope lives in a ContextVar, not a module global. A global saved and restored around the
# `with` looks equivalent and is not: with two INTERLEAVED scopes (A enters, B enters, A exits,
# B exits) B's restore puts back the dict A had already closed, and the cache stays open with no
# scope alive -- process-wide and never cleared, which is the exact failure this design exists to
# prevent. Reproduced with a ThreadPoolExecutor running `main()` over several roots, the most
# plausible embedder shape there is. A ContextVar is per-thread and per-task, so each run gets its
# own scope and `reset(token)` cannot clobber anyone else's.
#
# The single hottest `resolve()` in a real run is NOT memoised and stays that way on purpose:
# `frontmatter_index.iter_markdown_files` uses `resolve(strict=True)`, which raises instead of
# returning, and issues one call per file with no repeats to save. Measured on a ~3,900-file tree it
# is ~45% of all raw resolutions -- so this cache covers the repeats, not the total.
_RESOLVE_CACHE: ContextVar[Optional[Dict[str, Path]]] = ContextVar(
    "darnlink_resolve_cache", default=None)


@contextmanager
def resolve_cache() -> Iterator[None]:
    """Open a scope in which `resolved()` memoises. Nesting reuses the scope already open and owns
    nothing; leaving the outermost one drops every entry, so a cached resolution does not outlive
    the run that made it -- including when several runs share a process on different threads --
    provided the scope is left normally. A generator that opens one and is abandoned mid-yield keeps
    it open until it is collected, like any other context manager."""
    if _RESOLVE_CACHE.get() is not None:
        yield                       # nested: reuse, own nothing
        return
    token = _RESOLVE_CACHE.set({})
    try:
        yield
    finally:
        _RESOLVE_CACHE.reset(token)


def resolved(path: Path) -> Path:
    """`path.resolve()`, memoised only while a `resolve_cache()` scope is open (see the note above).

    Outside a scope, and for relative paths, this is exactly `path.resolve()`."""
    cache = _RESOLVE_CACHE.get()
    if cache is None or not path.is_absolute():
        return path.resolve()
    key = str(path)
    hit = cache.get(key)
    if hit is None:
        hit = path.resolve()
        cache[key] = hit
    return hit


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
    return resolved(linking_file.parent / path_part)


def relative_link(target: Path, linking_file: Path, fragment: str = "") -> str:
    """Path to `target` written relative to the directory of `linking_file`, POSIX style.

    Re-appends `#fragment` if given. This is the value to write inside `(...)`.
    """
    rel = os.path.relpath(resolved(target), start=resolved(linking_file.parent))
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
