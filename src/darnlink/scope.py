"""Write scope (feature 010): which files an invocation may modify.

`--only` narrows the **write** scope without touching the **index** scope. The tree is still walked
and indexed in full — a link's target usually lives outside the caller's own subtree, and narrowing
the *scan* is exactly what makes anchoring fail — but only the named files are rewritten.

A scope of `None` means "no narrowing": every scanned file may be written, which is the historical
behaviour and stays the default.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, List, Optional, Set


class ScopeError(ValueError):
    """A `--only` path that cannot be part of a write scope (FR-003)."""


def read_paths_from(source: str) -> List[str]:
    """Newline-separated paths from `source`; `-` reads stdin.

    This is how a caller passes a *generated* list (e.g. staged files) without darnlink learning
    where the list came from — it knows nothing about git (Constitution I/III).
    """
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise ScopeError(f"--only-from: cannot read {source}: {exc}") from exc
    return [line.strip() for line in text.splitlines() if line.strip()]


def resolve_write_scope(paths: Iterable[str], root: Path) -> Optional[Set[Path]]:
    """Resolve `--only` paths against the CWD and validate them (FR-003). Empty input -> `None`.

    Every path must exist, be a `.md` file, and live inside `root`. An unmatched path is an error
    rather than a no-op on purpose: silently ignoring it would turn a typo — or a stale entry in a
    generated list — into a green run that wrote nothing.
    """
    paths = list(paths)
    if not paths:
        return None
    root = root.resolve()
    scope: Set[Path] = set()
    for raw in paths:
        p = Path(raw).resolve()
        if not p.exists():
            raise ScopeError(f"--only: no such file: {raw}")
        if not p.is_file() or p.suffix.lower() != ".md":
            raise ScopeError(f"--only: not a Markdown file: {raw}")
        if not p.is_relative_to(root):
            raise ScopeError(f"--only: outside the scanned root ({root}): {raw}")
        scope.add(p)
    return scope


def in_scope(path: Path, scope: Optional[Set[Path]]) -> bool:
    """True if `path` may be written (always true when there is no narrowing)."""
    return scope is None or path.resolve() in scope
