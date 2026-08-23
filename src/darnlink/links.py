"""Robust-link grammar: detect, parse and emit.

Grammar (ported from the predecessor `tx_aiready_mdlink`):
    [text](href) <!-- uuid: <36-char-uuid> -->
Detection tolerates any whitespace between `)` and the comment; emission uses a single space.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# The BODY of a pandoc attribute block, between its own `{` and `}` — one definition, shared by
# ROBUST_LINK_RE's `attrs` group below and by `_PANDOC_ATTR_RE` further down. `[^{}\n]*` alone (the
# first version of this pattern) treats a `}` inside a quoted attribute value as the block's own
# closing brace and cuts the match short there — not a miss, a WRONG match, and a corrupting one
# once something is spliced at the point it stopped. `"[^"\n]*"` makes a quoted run atomic, so `{`
# and `}` inside a quote no longer terminate the block early; an unterminated quote still fails the
# whole match, same as an unbalanced `{` always did. Kept as ONE definition on purpose — two
# independent copies of "what an attrs block looks like" is exactly the shape that drifted before
# (`is_local_relative`'s four call sites, FR-052), and it already drifted once here: an earlier
# revision of this fix updated only `_PANDOC_ATTR_RE` and left this literal on the old, corrupting
# pattern, so `repair` silently stopped recognising (and therefore stopped fixing) an already-correct
# robust link whose attrs held a quoted `}` — no finding, no write, the stale path just stayed stale.
_PANDOC_ATTR_BODY = r'(?:[^{}"\n]|"[^"\n]*")*'

# A robust link: a Markdown link immediately followed (any whitespace) by a uuid HTML comment.
# The optional `attrs` group is a pandoc attribute block (`{.cls}`, `{width="1in"}`, …): pandoc
# requires it immediately after the link's `)`, with no whitespace, so it must be matched BEFORE
# the anchor comment's leading `\s*` — reversing the order would let the whitespace class absorb
# right up to `{`, misparsing `[x](y){.cls}` as `[x](y)` followed by unrelated `{.cls}` text.
ROBUST_LINK_RE = re.compile(
    r"\[(?P<text>[^\]]*)\]\((?P<href>(?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))+|[^)]+)\)"
    r"(?P<attrs>\{" + _PANDOC_ATTR_BODY + r"\})?\s*<!--\s*uuid:\s*(?P<uuid>[0-9a-fA-F-]{36})\s*-->"
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
# A pandoc attribute block immediately following a link's `)`, no whitespace allowed (pandoc's own
# rule -- a block after a space is not attached to anything and pandoc ignores it). Matched with
# .match(content, pos) the same way as _TRAILING_UUID_RE, so callers can skip past it before
# checking for the anchor comment -- see `_skip_attrs` below for why that skip has to exist at all.
# Shares `_PANDOC_ATTR_BODY` with `ROBUST_LINK_RE`'s own `attrs` group (see that constant's comment
# for why one definition, not two, matters here specifically).
_PANDOC_ATTR_RE = re.compile(r"\{" + _PANDOC_ATTR_BODY + r"\}")


def pandoc_attrs_at(content: str, pos: int) -> str:
    """The pandoc attribute block immediately at `pos`, verbatim, or `""` if there is none.

    Used both to WRITE (place the block before the anchor) and to DETECT (skip past it before
    checking for a trailing anchor comment) -- one definition of "attrs block" for both directions,
    so they cannot drift apart the way `is_local_relative`'s four call sites once did (FR-052).
    """
    m = _PANDOC_ATTR_RE.match(content, pos)
    return m.group(0) if m else ""


def _skip_attrs(content: str, pos: int) -> int:
    """`pos`, advanced past an immediately-following pandoc attribute block if there is one.

    Every site that decides "is a link already robust?" by looking right after its `)` has to use
    this, not `pos` itself -- once `--write` places attrs before the anchor (FR-065), a link that
    HAS an attrs block reads `[x](y){.cls} <!-- uuid: … -->`, and checking for the anchor at `pos`
    (right after the `)`, before `{.cls}`) would find `{` instead and call the link still plain.
    Robustify would then append a SECOND anchor: the uuid ends up in the file twice, one copy
    anchoring nothing, invisible to every later run because the link now reads as robust either way.
    """
    return pos + len(pandoc_attrs_at(content, pos))
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


# --- Feature 017: destinations carried by a diagram's `click` directives ---------------------
#
# These live next to the region computation they depend on, and DELIBERATELY know nothing about
# web links: they yield `(offset, destination)`, so `links.py` never has to import `weblinks.py`
# and there is no second notion of what a fenced block is (FR-054).

#: `click <id> ["href"] "<dest>" [target|"tooltip"]` -- the only forms that carry a destination.
#: Measured over 2165 real directives, three shapes account for every one of them, each on a single
#: line with the destination double-quoted. That is a REGULAR language: no nesting, no recursion,
#: which is why a grammar engine was evaluated and rejected (research R1). A directive that binds a
#: callback (`call cb()` / `callback`) carries no destination and simply does not match (FR-057).
# --- Recognising a `click` directive: a LINE READER, deliberately not a regular expression ------
#
# The first implementation used one, and two of the three defects review found in this feature came
# from regex semantics rather than from the language being hard: an `^` anchor that made a guard
# unreachable, and that same `^` compiled without MULTILINE while used through `.match(pos)`, which
# only ever matches at index 0. Neither mistake is possible below, because none of those concepts
# exist here. The language is line-oriented and tiny; reading it as lines is both simpler and the
# "traditional, auditable algorithm a human can verify" the constitution asks for (Principle IV).


def _statement_starts(line: str) -> List[int]:
    """Offsets within the line where a statement may begin: the start, and after each `;`.

    ⚠️ NO quote tracking, and that is the fix for a regression this file already had. Carrying a
    running "am I inside quotes" flag across a whole physical line means one stray or unpaired quote
    -- a typo in a node label, a half-pasted destination -- silently swallows every statement after
    it, including well-formed `click` directives. A destination dying unnoticed because of an
    unrelated typo earlier on the line is precisely the harm this feature exists to prevent.

    Nothing is lost by dropping it: a destination containing `;` still survives, because the
    destination is delimited by its own quotes in `_click_destination`, which searches forward for
    the closing one and does not care about separators. An offset that is not the start of a
    directive simply fails to parse and is discarded."""
    out = [0]
    out.extend(i + 1 for i, ch in enumerate(line) if ch == ";")
    return out


def _click_destination(statement: str) -> Optional[Tuple[str, int]]:
    """`(destination, offset just past its closing quote)` for one `click` statement, or None.

    The second element is what lets the caller know how much of the line this directive CONSUMED,
    so a `;` living inside the destination cannot be mistaken for the start of another statement.

    Accepts `click <id> "<dest>" ...` and `click <id> href "<dest>" ...`; a trailing target or
    tooltip is irrelevant. Returns None for a directive that binds a callback (`call cb()`,
    `callback`), which carries no destination at all (FR-057)."""
    rest = statement.lstrip(" \t")
    if not rest.startswith("click"):
        return None
    rest = rest[len("click"):]
    if rest[:1] not in (" ", "\t"):
        return None  # `clickable`, `clicked`, ... are not the directive
    rest = rest.lstrip(" \t")
    node_end = 0
    while node_end < len(rest) and rest[node_end] not in " \t":
        node_end += 1
    if node_end == 0:
        return None  # no node id
    rest = rest[node_end:].lstrip(" \t")
    if rest.startswith("href") and rest[4:5] in (" ", "\t"):
        rest = rest[4:].lstrip(" \t")
    if not rest.startswith('"'):
        return None  # a callback binding, or anything else that is not a quoted destination
    close = rest.find('"', 1)
    if close == -1:
        return None  # an unterminated quote is not a destination
    dest = rest[1:close]
    if not dest:
        return None
    return dest, len(statement) - len(rest) + close + 1


def mermaid_region_bodies(content: str) -> List[Span]:
    """Spans of the BODY of each fenced block whose info string names `mermaid` (FR-054).

    Derived from `_fenced_code_spans()`, never computed independently: everything hard about the
    boundary -- unclosed fence to EOF, closing fence of equal-or-greater length, tildes vs
    backticks, an example fence nested in a longer one -- is inherited for free, and a second
    computation could drift from the one the write axis obeys.

    The body starts after the opening fence's line, so the info string itself is never scanned.
    Pure & deterministic."""
    out: List[Span] = []
    for start, end in _fenced_code_spans(content):
        nl = content.find("\n", start)
        if nl == -1 or nl >= end:
            continue  # a fence with no body (or an opener at EOF) carries nothing
        info = content[start:nl].lstrip(" ").lstrip("`~").strip().lower()
        if info.startswith("mermaid"):
            out.append((nl + 1, end))
    return out


def mermaid_click_destinations(content: str) -> List[Tuple[int, str]]:
    """`(absolute offset of the directive, destination)` for every `click` inside a mermaid region.

    The offset is into the FILE, not into the region body: a report has to point at a place a human
    can find. Pure & deterministic -- no network, no heuristics (FR-058)."""
    out: List[Tuple[int, str]] = []
    for body_start, body_end in mermaid_region_bodies(content):
        body = content[body_start:body_end]
        line_start = 0
        for line in body.splitlines(keepends=True):
            # A diagram comments with `%%`. Checked once per LINE, before anything is parsed, so a
            # comment cannot contribute a destination however it is written (FR-056).
            if line.lstrip(" \t").startswith("%%"):
                line_start += len(line)
                continue
            # A `;` that lives INSIDE a destination is not the start of anything. Skipping the
            # span a directive already consumed is what stops a quote embedded after such a `;`
            # from fabricating a second, phantom destination out of text that was never a link.
            consumed_until = 0
            for offset in _statement_starts(line):
                if offset < consumed_until:
                    continue
                statement = line[offset:]
                found = _click_destination(statement)
                if found is not None:
                    dest, end = found
                    lead = len(statement) - len(statement.lstrip(" \t"))
                    out.append((body_start + line_start + offset + lead, dest))
                    consumed_until = offset + end
            line_start += len(line)
    return out


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
    start: int  # span of the whole robust link (link + attrs + comment) in the source
    end: int
    attrs: str = ""  # a pandoc attribute block (`{.cls}`), verbatim, or "" if there is none


@dataclass(frozen=True)
class PlainLink:
    text: str
    href: str
    start: int  # span of just the [text](href) in the source
    end: int


def find_robust_links(content: str, ignore: Sequence[Span] = ()) -> List[RobustLink]:
    """All robust links in the content, in document order, skipping any inside `ignore` spans."""
    return [
        RobustLink(m.group("text"), m.group("href"), m.group("uuid").lower(), m.start(), m.end(),
                   m.group("attrs") or "")
        for m in ROBUST_LINK_RE.finditer(content)
        if not _in_spans(m.start(), ignore)
    ]


def find_plain_links(content: str, ignore: Sequence[Span] = ()) -> List[PlainLink]:
    """All Markdown links that are NOT already robust, skipping any inside `ignore` spans."""
    out: List[PlainLink] = []
    for m in MD_LINK_RE.finditer(content):
        if _TRAILING_UUID_RE.match(content, _skip_attrs(content, m.end())):
            continue  # this link (with or without a pandoc attrs block) is already robust; skip
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
        after_attrs = _skip_attrs(content, m.end())
        t = _TRAILING_UUID_RE.match(content, after_attrs)
        if t is None:
            continue
        c = UUID_COMMENT_RE.search(content, after_attrs, t.end())
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


def emit_robust_link(text: str, href: str, uuid: str, attrs: str = "") -> str:
    """Canonical robust-link rendering: a single space before the comment.

    `attrs` (a pandoc attribute block, `{.cls}`) goes immediately after `)`, with NO space -- pandoc
    only recognises the block there (FR-065). Putting the anchor comment first, as earlier versions
    did unconditionally, detaches `{.cls}` from the link it belongs to: pandoc then ignores it
    silently, and the document still renders, just without the class/width/height it was given.
    """
    return f"[{text}]({href}){attrs} <!-- uuid: {uuid} -->"
