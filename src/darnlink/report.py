"""Findings produced by a scan (what darnlink would do / could not do)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Kind(str, Enum):
    REPAIR = "repair"              # a robust link whose path is stale and can be fixed
    CONFLICT = "conflict"          # robust link whose path resolves to a real file, but the uuid lives in a DIFFERENT file: the two halves disagree (likely a mis-pasted uuid) — left untouched for human review
    ROBUSTIFY = "robustify"        # a plain link that can be upgraded to robust
    UNRESOLVABLE = "unresolvable"  # robust link whose uuid is in no file
    AMBIGUOUS = "ambiguous"        # robust link whose uuid is in more than one file
    NO_FRONTMATTER = "no_frontmatter"  # robustify target has no frontmatter (needs --create-frontmatter)
    DENY_LISTED = "deny_listed"        # robustify target matches --no-create-frontmatter-for: never given a uuid
    IGNORED_LINKS = "ignored_links"    # source carries <!-- darnlink-ignore-links -->: its own links are left alone (it stays a target)
    INVALID_FRONTMATTER = "invalid_frontmatter"  # frontmatter present but not valid YAML; reported, never touched


@dataclass(frozen=True)
class Finding:
    kind: Kind
    file: Path        # the file the finding is about: the linking file for link findings,
                      # or the file itself for file-level findings (e.g. invalid_frontmatter)
    detail: str       # human-readable summary (e.g. "old.md -> ../new.md")
