"""Path helpers: split fragments and compute a link path relative to the linking file."""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple
from urllib.parse import quote, unquote


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

    Outside a scope, and for relative paths, this is exactly `path.resolve()`.

    A path with a NUL is the exception: no file name can hold one, and `resolve()` raises on it on Linux and
    takes it on Windows with 3.13. It is made absolute without asking the system, so every caller gets the
    same path everywhere, and the `exists()`/`is_file()` that follow answer False."""
    if "\0" in str(path):
        return Path(os.path.normpath(os.path.abspath(path)))
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


#: A CommonMark backslash escape: a backslash before ASCII punctuation stands for that character.
_BACKSLASH_ESCAPE_RE = re.compile(r"\\([!-/:-@\[-`{-~])")


def destination_path(path_part: str) -> str:
    """The file name a link destination's path part denotes: backslash escapes undone, then
    percent-decoded. `A \\(Z\\)` and `A%20%28Z%29` both name `A (Z)`.

    The order is CommonMark's: escapes belong to the Markdown source, and what is left is a URL
    reference, whose `%XX` a browser decodes when it asks for the file. A backslash before anything
    that is not ASCII punctuation is a literal backslash and is kept."""
    return unquote(_BACKSLASH_ESCAPE_RE.sub(r"\1", path_part))


def resolve_href(href: str, linking_file: Path, decode: bool = True) -> Path:
    """Absolute path the href points to, resolved relative to the linking file's directory.

    The fragment is dropped. Returns a resolved (normalized) path; the target need not exist.

    With `decode` (the default, for a Markdown link destination) the href is read as
    `destination_path` reads it (escapes undone, `%XX` decoded) -- the ONE place where a
    destination becomes a path, so robustify, repair and the dangling axis agree. When that path
    does not exist but the href taken literally does (a file really named `100%25.md`, a Windows
    path written with backslashes), the literal one is returned: that link worked before this
    function decoded anything, and it keeps working.

    Decoding never changes what KIND of href it is: when the decoded spelling is absolute or carries
    a scheme and the literal one does not (`%2Fetc%2Fpasswd`, `\\/home/x.md`), or the other way
    round, the literal spelling is used. Joining an absolute path onto the linking directory would
    silently drop that directory, and a link to `/etc/passwd` would resolve -- and be anchored --
    as if it were relative. `is_local_relative` rejects those hrefs for the same reason.

    `decode=False` is the literal reading, for values that are not Markdown destinations (a YAML
    `link:`, see `yaml_refs`).
    """
    path_part, _ = split_fragment(href)
    decoded = destination_path(path_part) if decode else path_part
    if decoded != path_part and _relative_shape(decoded) != _relative_shape(path_part):
        decoded = path_part
    t = resolved(linking_file.parent / decoded)
    if decoded == path_part or t.exists():
        return t
    literal = resolved(linking_file.parent / path_part)
    return literal if literal.exists() else t


def relative_link(target: Path, linking_file: Path, fragment: str = "") -> str:
    """Path to `target` written relative to the directory of `linking_file`, POSIX style.

    Re-appends `#fragment` if given. This is the value to write inside `(...)`.
    """
    rel = os.path.relpath(resolved(target), start=resolved(linking_file.parent))
    rel_posix = Path(rel).as_posix()
    return f"{rel_posix}#{fragment}" if fragment else rel_posix


#: What stays literal when darnlink percent-encodes a link part (a JSON Pointer fragment, a path in
#: a percent-encoded destination): RFC 3986 unreserved characters and sub-delimiters, plus `/`,
#: `:` and `@`, minus the parentheses -- which end a Markdown destination -- and so also `#`, `?`,
#: `%` and the space.
URL_SAFE = "/~-._!$&'*+,;=:@"


def pointer_fragment(pointer: str) -> str:
    """A JSON Pointer written as the fragment of a link: percent-encoded, so a key with a space, a parenthesis or a
    `#` cannot end a Markdown link destination (reading compares the decoded fragment)."""
    return quote(pointer, safe=URL_SAFE)


def is_web_href(href: str) -> bool:
    """True if href is an absolute web URL (http/https). Feature 013: the core repair/check path must
    skip robust links whose href is a URL — their uuid may live in ANOTHER repo, which the core never
    scans, so treating them as local would wrongly report them `unresolvable`. Cross-repo web links are
    handled only by the opt-in `web-check` subcommand (specs/013-web-robustness)."""
    return href.strip().lower().startswith(("http://", "https://"))


def _relative_shape(path_part: str) -> bool:
    """True if a path part looks like a relative path: not empty, no scheme, not absolute."""
    if not path_part:
        return False  # bare #fragment
    low = path_part.lower()
    if "://" in low or low.startswith(("http:", "https:", "mailto:", "ftp:", "/")):
        return False
    return True


def is_local_relative(href: str) -> bool:
    """True if href is a relative link into the local tree (not a URL, mailto, absolute or bare
    `#anchor`). Says nothing about what the path names — a `.md` file, a directory, anything.

    Both spellings are judged: the href as written AND as `destination_path` decodes it. An encoded
    or escaped absolute path (`%2Fhome%2Fx.md`, `\\/home/x.md`) or scheme (`http%3A//x`) is not
    relative, whatever it looks like before decoding -- otherwise every caller that resolves it
    would reach a file outside the tree and treat it as a local target."""
    path_part, _ = split_fragment(href)
    if not _relative_shape(path_part):
        return False
    decoded = destination_path(path_part)
    return decoded == path_part or _relative_shape(decoded)


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
    link that was actually fine. This is the ONLY strip in the resolution path: `resolve_href` does
    not strip, so a link whose destination genuinely differs only by that space still
    fails to resolve to the real file and gets corrected by the normal repair-a-stale-link path, not
    silently treated as already-correct.

    Whitespace around a destination no longer reaches this function from a Markdown link: the link
    scanner (`links.scan_links`, the #74 work) reads `[x]( B.md )` as `B.md`, as CommonMark does, so
    `_anchor_target` and `_dir_link_missing_readme` -- the two sites #67 deferred -- see the clean
    destination too. The strip stays for hrefs that come from elsewhere. The suffix is judged on the
    decoded name (`destination_path`), the same spelling every resolution uses.
    """
    path_part, _ = split_fragment(href)
    return destination_path(path_part).strip().lower().endswith(".md")
