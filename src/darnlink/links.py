"""Robust-link grammar: detect, parse and emit.

Grammar (ported from the predecessor `tx_aiready_mdlink`):
    [text](href) <!-- uuid: <36-char-uuid> -->
Detection tolerates any whitespace between `)` and the comment; emission uses a single space.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

# A robust link: a Markdown link immediately followed (any whitespace) by a uuid HTML comment.
ROBUST_LINK_RE = re.compile(
    r"\[(?P<text>[^\]]+)\]\((?P<href>[^)]+)\)\s*<!--\s*uuid:\s*(?P<uuid>[0-9a-fA-F-]{36})\s*-->"
)
# Any inline Markdown link.
MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<href>[^)]+)\)")
# A uuid comment that immediately follows a link (used to tell plain from robust).
# No `^`: it is applied with .match(content, pos), which already anchors at pos.
_TRAILING_UUID_RE = re.compile(r"\s*<!--\s*uuid:\s*[0-9a-fA-F-]{36}\s*-->")

Span = Tuple[int, int]


def ignored_spans(content: str, block_markers: Sequence[str]) -> List[Span]:
    """Spans of generated blocks to ignore: between `<!-- NAME-start -->` and `<!-- NAME-end -->`.

    Lets darnlink leave machine-generated regions (e.g. a generator's auto-built tables) untouched
    so it only operates on hand-authored prose links.
    """
    spans: List[Span] = []
    for name in block_markers:
        pat = re.compile(
            rf"<!--\s*{re.escape(name)}-start\s*-->.*?<!--\s*{re.escape(name)}-end\s*-->",
            re.DOTALL,
        )
        spans.extend((m.start(), m.end()) for m in pat.finditer(content))
    return spans


def _in_spans(pos: int, spans: Sequence[Span]) -> bool:
    return any(s <= pos < e for s, e in spans)


def _fenced_code_spans(content: str) -> List[Span]:
    """Spans of fenced code blocks: ```` ``` ````/`~~~` (indent <=3), closed by the same fence char
    of equal-or-greater length. An info string after the opener is allowed. An unclosed fence
    extends to EOF (over-ignoring is safe; corrupting code is not -- FR-016)."""
    spans: List[Span] = []
    pos = 0
    fence: Tuple[str, int, int] | None = None  # (char, length, start offset)
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if fence is None:
            if indent <= 3 and stripped[:3] in ("```", "~~~"):
                ch = stripped[0]
                run = len(stripped) - len(stripped.lstrip(ch))
                if run >= 3:
                    fence = (ch, run, pos)
        else:
            ch, run, start = fence
            body = stripped.rstrip()
            # a closing fence is only fence chars, of the same kind, length >= the opener
            if indent <= 3 and body and set(body) == {ch} and len(body) >= run:
                spans.append((start, pos + len(line)))
                fence = None
        pos += len(line)
    if fence is not None:
        spans.append((fence[2], len(content)))  # unclosed -> to EOF
    return spans


def _inline_code_spans(content: str, skip: Sequence[Span]) -> List[Span]:
    """Spans of inline code: a run of N backticks closed by the next run of exactly N backticks
    (FR-017). An unterminated run is not code. Positions inside `skip` (fenced blocks) are not
    scanned, so backticks inside a fence never pair with backticks outside it."""
    spans: List[Span] = []
    n = len(content)
    i = 0
    while i < n:
        if content[i] != "`" or _in_spans(i, skip):
            i += 1
            continue
        j = i
        while j < n and content[j] == "`":
            j += 1
        run = j - i
        # look for a closing run of exactly `run` backticks
        k = j
        closed = False
        while k < n:
            if _in_spans(k, skip):
                break  # reached a fenced block; an inline span cannot cross it -> unterminated
            if content[k] == "`":
                m = k
                while m < n and content[m] == "`":
                    m += 1
                if m - k == run:
                    spans.append((i, m))
                    i = m
                    closed = True
                    break
                k = m
            else:
                k += 1
        if not closed:
            i = j  # unterminated opener; not a code span
    return spans


def code_spans(content: str) -> List[Span]:
    """All spans that are code (fenced blocks + inline code). Links starting inside any of these
    are examples, not navigational links, and must never be rewritten (FR-015). Pure & deterministic."""
    fenced = _fenced_code_spans(content)
    return fenced + _inline_code_spans(content, fenced)


# A whole-file opt-out: a file carrying this marker is removed from the darnlink graph entirely.
IGNORE_FILE_MARKER = "<!-- darnlink-ignore-file -->"
_IGNORE_FILE_RE = re.compile(r"<!--\s*darnlink-ignore-file\s*-->")


def file_is_ignored(content: str) -> bool:
    """True if the file opts out of darnlink via a `<!-- darnlink-ignore-file -->` marker that is
    NOT inside a code span (so a file documenting the marker as an example does not self-ignore).
    FR-019..FR-021; composes with code_spans (feature 002). Pure & deterministic."""
    code = code_spans(content)
    return any(not _in_spans(m.start(), code) for m in _IGNORE_FILE_RE.finditer(content))


# A SOURCE-only opt-out: darnlink never rewrites the links inside this file, but the file stays a
# first-class target (its uuid is indexed, so inbound robust links resolve and heal). This is the
# axis `darnlink-ignore-file` fuses: that one also drops the file as a target (FR-019), which the
# motivating case — a generated, heavily-linked INDEX.md — cannot afford. Feature 006.
IGNORE_LINKS_MARKER = "<!-- darnlink-ignore-links -->"
_IGNORE_LINKS_RE = re.compile(r"<!--\s*darnlink-ignore-links\s*-->")


def file_ignores_links(content: str) -> bool:
    """True if the file opts its OWN links out via a `<!-- darnlink-ignore-links -->` marker that is
    NOT inside a code span. Says nothing about the target axis: the file keeps its uuid indexed.
    FR-033/FR-036/FR-037; composes with code_spans (feature 002). Pure & deterministic.

    Note (FR-040): the marker must not precede the frontmatter block — the canonical reader only
    recognises a *leading* `---`, so a marker on line 1 would hide the file's own uuid and silently
    cost it the target axis. Detection itself is position-free; the ordering is a property of the
    frontmatter format, not of this check."""
    code = code_spans(content)
    return any(not _in_spans(m.start(), code) for m in _IGNORE_LINKS_RE.finditer(content))


@dataclass(frozen=True)
class RobustLink:
    text: str
    href: str
    uuid: str
    start: int  # span of the whole robust link (link + comment) in the source
    end: int


@dataclass(frozen=True)
class PlainLink:
    text: str
    href: str
    start: int  # span of just the [text](href) in the source
    end: int


def find_robust_links(content: str, ignore: Sequence[Span] = ()) -> List[RobustLink]:
    """All robust links in the content, in document order, skipping any inside `ignore` spans."""
    return [
        RobustLink(m.group("text"), m.group("href"), m.group("uuid").lower(), m.start(), m.end())
        for m in ROBUST_LINK_RE.finditer(content)
        if not _in_spans(m.start(), ignore)
    ]


def find_plain_links(content: str, ignore: Sequence[Span] = ()) -> List[PlainLink]:
    """All Markdown links that are NOT already robust, skipping any inside `ignore` spans."""
    out: List[PlainLink] = []
    for m in MD_LINK_RE.finditer(content):
        if _TRAILING_UUID_RE.match(content, m.end()):
            continue  # this link is part of a robust link; skip
        if _in_spans(m.start(), ignore):
            continue  # inside a generated block (e.g. autogrid); leave it alone
        out.append(PlainLink(m.group("text"), m.group("href"), m.start(), m.end()))
    return out


def emit_robust_link(text: str, href: str, uuid: str) -> str:
    """Canonical robust-link rendering: a single space before the comment."""
    return f"[{text}]({href}) <!-- uuid: {uuid} -->"
