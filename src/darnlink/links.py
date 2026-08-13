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
    r"\[(?P<text>[^\]]*)\]\((?P<href>(?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))+|[^)]+)\)\s*<!--\s*uuid:\s*(?P<uuid>[0-9a-fA-F-]{36})\s*-->"
)
# Any inline Markdown link. `text` is `*`, not `+`: `[](dest)` is a link with empty text, and the
# empty alt of `![](dest)` is what pandoc emits for every image in a converted .docx/.odt. Requiring
# one character there made the whole link invisible -- not reported as bad, *absent* -- so a tree
# full of broken image embeds passed the dangling axis as clean (FR-051). `href` stays `+`: a link
# with no destination at all has nothing to check.
#: The destination may contain BALANCED parentheses — CommonMark says so, and filenames from
#: document systems are full of them (`Log%20Analysis%20(February).docx`). `[^)]+` stopped at
#: the first `)`, truncating the path and reporting it dead while the file was on disk. Measured
#: on the fleet: **266** links of that shape. The report concealed the cut, because its own
#: `(resolves to …)` wrapper supplied the missing parenthesis and the path read as complete.
#:
#: ⚠️ **Bounded at two levels of nesting, and that bound is a known limit, not a property.**
#: CommonMark allows arbitrary depth; a regex cannot. Adjudicated against the reference
#: implementation: `[^)]+` agrees with `cmark` on 3 of 9 probe shapes, one level on 7, two on 8.
#: The ninth is triple nesting, which no bounded pattern reaches — it needs the scanner tracked
#: in #74, and it occurs 0 times in the fleet.
#:
#: ⚠️ **Two guards, and both exist because the first version of this change produced a FALSE
#: GREEN — the outcome its own comment declared unacceptable.**
#:
#: * `[^()\s]`, not `[^()]`. A destination outside `<…>` cannot contain whitespace; CommonMark
#:   says so, and without that exclusion the balanced branch pairs an *unmatched* `(` with the
#:   link's own `)` and keeps running — across lines — until some later lone `)`. Everything
#:   between is absorbed, and because `finditer` never restarts inside a match, a healthy link
#:   caught in that span **ceases to exist for the tool**. Measured: `[a](f(x.md) blah [b](t.md)
#:   tail)` lost `t.md` entirely. Excluding whitespace makes the branch fail at the first space,
#:   so such input falls to the fallback and behaves exactly as it did before this change.
#: * The trailing `|[^)]+`. Without it, a link nested past the bound stops matching at all —
#:   invisible again, by the other route.
#:
#: Both restore the OLD truncating behaviour rather than silence: still wrong, still visible,
#: still reported. **Never trade a false red for a false green.**
#:
#: ⚠️ **The swallow class is NARROWED, not closed, and saying otherwise would be the same kind of
#: false claim this pattern exists to avoid.** Two producers survive, both handing an unmatched `(`
#: with no whitespace in the absorbed span:
#:
#: * a **backslash-escaped** `\(` — CommonMark's own way to write a literal paren, which this
#:   pattern has no escape handling for and reads as an opener;
#: * an **angle-bracket destination** `(<…(…>)` — there is no `<…>` branch here at all, which is
#:   awkward precisely because the whitespace rule above cites `<…>` as its exception.
#:
#: What bounds the harm: the merged destination never resolves, so the gate stays RED. It is an
#: under-count with a mangled target name, not a green gate — N findings collapse to 1. The sharper
#: cost is on the web axis, where the swallowed neighbours stop being fetched at all. Measured
#: across 13.984 files in the gated fleet: **0 escaped-paren destinations, 0 angle destinations
#: containing a paren, 0 adjacent-link shapes**. Closing it needs the scanner in #74.
#:
#: And the whitespace class is **wider than CommonMark's**: `\s` is Unicode-aware, while cmark
#: terminates a destination only on ASCII space, tab and newline — it accepts NBSP, `\v`, `\f`,
#: U+2000–200A and others as ordinary characters. So 12 characters are excluded needlessly. Kept
#: because measured: with no parens the fallback returns those destinations byte-perfect (14/14),
#: and with parens the result is exactly the old truncation. Nothing becomes invisible; the cost is
#: precision, not safety.
MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<href>(?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))+|[^)]+)\)")
# A uuid comment that immediately follows a link (used to tell plain from robust).
# No `^`: it is applied with .match(content, pos), which already anchors at pos.
_TRAILING_UUID_RE = re.compile(r"\s*<!--\s*uuid:\s*[0-9a-fA-F-]{36}\s*-->")
# Any uuid comment, wherever it sits. Used to find the ones attached to nothing.
UUID_COMMENT_RE = re.compile(r"<!--\s*uuid:\s*(?P<uuid>[0-9a-fA-F-]{36})\s*-->")

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


def _carries_marker(content: str, keyword: str, marker_re: "re.Pattern[str]") -> bool:
    """True if `marker_re` matches outside a code span (so a file documenting the marker as an
    example does not opt itself out). Pure & deterministic.

    The `keyword` substring test is a cheap reject: markers are rare, and `code_spans()` parses the
    whole file, so the common case (no marker at all) must not pay for it. It is safe because every
    marker regex requires that keyword literally — a file that lacks the substring cannot match."""
    if keyword not in content:
        return False
    code = code_spans(content)
    return any(not _in_spans(m.start(), code) for m in marker_re.finditer(content))


# A whole-file opt-out: a file carrying this marker is removed from the darnlink graph entirely.
IGNORE_FILE_MARKER = "<!-- darnlink-ignore-file -->"
_IGNORE_FILE_RE = re.compile(r"<!--\s*darnlink-ignore-file\s*-->")


def file_is_ignored(content: str) -> bool:
    """True if the file opts out of darnlink via a `<!-- darnlink-ignore-file -->` marker that is
    NOT inside a code span (so a file documenting the marker as an example does not self-ignore).
    FR-019..FR-021; composes with code_spans (feature 002). Pure & deterministic."""
    return _carries_marker(content, "darnlink-ignore-file", _IGNORE_FILE_RE)


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
    return _carries_marker(content, "darnlink-ignore-links", _IGNORE_LINKS_RE)


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


@dataclass(frozen=True)
class DetachedAnchor:
    uuid: str
    start: int  # span of just the `<!-- uuid: … -->` comment in the source
    end: int


def find_detached_anchors(content: str, ignore: Sequence[Span] = ()) -> List[DetachedAnchor]:
    """Every `<!-- uuid: … -->` that is NOT the trailing anchor of a Markdown link.

    The grammar only accepts whitespace between the link's `)` and the comment, so one token of
    inline markup in between -- a closing `**` is the common way to get this wrong -- leaves the
    comment attached to nothing while *looking* attached to a reader. The link is then still plain,
    and robustify would append a second comment carrying the same uuid: the file ends up with the
    uuid twice, one copy anchoring nothing, and every later run reports the tree clean.

    Like `find_plain_links`, this takes the spans to skip rather than computing them: the caller
    already has them. Passing the code spans matters more here than anywhere else -- a uuid comment
    shown as an example inside backticks must never be treated as a stray anchor, because acting on
    it means *deleting* text from someone's code sample.
    """
    attached: set[int] = set()
    for m in MD_LINK_RE.finditer(content):
        t = _TRAILING_UUID_RE.match(content, m.end())
        if t is None:
            continue
        c = UUID_COMMENT_RE.search(content, m.end(), t.end())
        if c is not None:
            attached.add(c.start())
    return [
        DetachedAnchor(m.group("uuid").lower(), m.start(), m.end())
        for m in UUID_COMMENT_RE.finditer(content)
        if m.start() not in attached and not _in_spans(m.start(), ignore)
    ]


def line_bounds(content: str, pos: int) -> Span:
    """The `[start, end)` of the line holding `pos`, end-exclusive of the newline."""
    start = content.rfind("\n", 0, pos) + 1
    end = content.find("\n", pos)
    return (start, len(content) if end == -1 else end)


def emit_robust_link(text: str, href: str, uuid: str) -> str:
    """Canonical robust-link rendering: a single space before the comment."""
    return f"[{text}]({href}) <!-- uuid: {uuid} -->"
