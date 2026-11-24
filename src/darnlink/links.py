"""Robust-link grammar: detect, parse and emit.

Grammar (ported from the predecessor `tx_aiready_mdlink`):
    [text](href) <!-- uuid: <36-char-uuid> -->
Detection tolerates any whitespace between `)` and the comment; emission uses a single space.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Tuple
from urllib.parse import quote

from .paths import URL_SAFE, destination_path, split_fragment

# The BODY of a pandoc attribute block, between its own `{` and `}`, used by `_PANDOC_ATTR_RE`
# further down. Before the link scanner (#74) robust-link detection carried a second copy of it
# inside `ROBUST_LINK_RE`; now both directions go through `_skip_attrs`, one definition by
# construction. `[^{}\n]*` alone (the first version of this pattern) treats a `}` inside a quoted
# attribute value as the block's own closing brace and cuts the match short there — not a miss, a
# WRONG match, and a corrupting one once something is spliced at the point it stopped. `"[^"\n]*"`
# makes a quoted run atomic, so `{` and `}` inside a quote no longer terminate the block early; an
# unterminated quote still fails the whole match, same as an unbalanced `{` always did. Kept as ONE
# definition on purpose — two independent copies of "what an attrs block looks like" is exactly the
# shape that drifted before (`is_local_relative`'s four call sites, FR-052), and it drifted once
# here: an earlier revision of this fix updated only `_PANDOC_ATTR_RE` and left the copy inside
# `ROBUST_LINK_RE` on the old, corrupting pattern, so `repair` silently stopped recognising (and
# therefore stopped fixing) an already-correct robust link whose attrs held a quoted `}` — no
# finding, no write, the stale path just stayed stale.
_PANDOC_ATTR_BODY = r'(?:[^{}"\n]|"[^"\n]*")*'

# --- Link scanner: where a Markdown link starts, where its destination is, where it ends --------
#
# Until #74 this was two regular expressions (`MD_LINK_RE`, `ROBUST_LINK_RE`). They accepted
# balanced parentheses only in a destination with no whitespace, nested at most two levels, with no
# idea of a backslash escape, of the `<…>` form or of a title. Anything else fell to `[^)]+`, which
# cut the destination at its first `)`: `[x](../A (Z)/)` read as `../A (Z`, a dead link to a folder
# that is on disk. Folders named `Foo (Bar)` are common in documents exported from other systems, so
# that was a stream of false findings, and `--write` turned it into broken files (#74).
#
# The scanner below reads the destination the way CommonMark does, and only falls back when
# CommonMark says "not a link". It is a plain left-to-right reader (Principle IV: an algorithm a
# human can check), and it has three rungs, tried in order at each `](`:
#
# 1. **CommonMark.** Optional whitespace, then a destination: either `<…>` (anything but a newline
#    or an unescaped `<`/`>`, so spaces and parentheses are fine) or a bare run with no ASCII space
#    or control character, in which a parenthesis must be balanced or backslash-escaped. Nesting is
#    capped at 32 levels, the bound cmark (the CommonMark reference implementation) applies; deeper
#    input falls to rung 2. The cap is what keeps the scan linear (see `scan_links`).
#    Then optionally whitespace and a title (`"…"`, `'…'`, `(…)`), optional whitespace, and `)`.
#    Whitespace around the destination is not part of it, so `[x]( B.md )` names `B.md`.
#
# 2. **One line, with spaces (a deliberate extension).** `[x](../A (Z)/)` is NOT a link in strict
#    CommonMark: a bare destination cannot hold a space, so a renderer prints it as text. But it is
#    exactly how a person writes a link to a folder called `A (Z)`, darnlink has always half-read
#    it, and reporting it as dead (or ignoring it) helps nobody. So when rung 1 fails, the whole
#    single-line run up to the `)` that balances the opening one is taken as the destination,
#    provided it holds no newline, no `[`/`]` (so it can never swallow a neighbouring link), no
#    `<`/`>` and no `"` outside a title. A trailing `"…"`/`'…'` title after whitespace, on the same
#    line and without `[`/`]`, is separated as in rung 1 (`[y](Foo (Bar)/ "T")`). The link then
#    validates and is anchored; `--write` keeps the author's spelling, because darnlink reads it
#    back the same.
#
# 3. **The old truncating fallback, `[^)]+`.** Kept on purpose for input that is neither: an
#    unbalanced `(` must still produce a link that is reported (with a mangled name) rather than
#    vanish. Never trade a false red for a false green.
#
# The `text` part is unchanged: `[^\]]*` (possibly empty: `![](img.png)` is what pandoc emits for
# every image of a converted document, FR-051), and the link starts at its `[`.

#: Characters a backslash can escape (CommonMark: ASCII punctuation). A backslash before anything
#: else is a literal backslash.
ASCII_PUNCTUATION = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

#: Characters that end rung 2 without a match (see the scanner notes above).
_LOOSE_STOP = frozenset("\n\r[]<>\"")


@dataclass(frozen=True)
class LinkMatch:
    """One `[text](destination)` found by `scan_links`.

    `href` is the destination as the author spelled it, minus the `<…>` brackets and minus any
    title: backslash escapes and `%XX` are still there (`paths.destination_path` turns it into a
    filesystem path). `inner_*` is the text between `(` and `)`; `dest_*` is the destination token
    within it, brackets included, so a rewrite can replace exactly that and keep the rest (spacing,
    title) byte for byte."""
    start: int        # the `[`
    end: int          # just past the `)`
    text: str
    href: str
    inner_start: int  # just past the `(`
    inner_end: int    # the `)`
    dest_start: int
    dest_end: int
    angle: bool       # the destination is written `<…>`


def _skip_space(s: str, i: int, n: int, newline: bool = True) -> int:
    """`i` advanced over spaces and tabs and, if `newline`, at most one line ending."""
    seen_newline = False
    while i < n:
        c = s[i]
        if c == " " or c == "\t":
            i += 1
        elif newline and not seen_newline and c in "\r\n":
            seen_newline = True
            i += 2 if (c == "\r" and i + 1 < n and s[i + 1] == "\n") else 1
        else:
            break
    return i


def _scan_angle(s: str, i: int, n: int) -> Optional[int]:
    """End (past `>`) of an angle destination starting at `s[i] == "<"`, or None."""
    j = i + 1
    while j < n:
        c = s[j]
        if c == "\\" and j + 1 < n and s[j + 1] in ASCII_PUNCTUATION:
            j += 2
            continue
        if c == ">":
            return j + 1
        if c in "<\n\r":
            return None
        j += 1
    return None


#: Deepest parenthesis nesting rung 1 accepts in a bare destination, as cmark does.
_MAX_PAREN_DEPTH = 32


def _scan_bare(s: str, i: int, n: int) -> Optional[int]:
    """End of a CommonMark bare destination starting at `i`, or None (empty, unbalanced, or nested
    deeper than `_MAX_PAREN_DEPTH`)."""
    depth = 0
    j = i
    while j < n:
        c = s[j]
        if c == "\\" and j + 1 < n and s[j + 1] in ASCII_PUNCTUATION:
            j += 2
            continue
        if c <= " " or c == "\x7f":
            break                      # ASCII space or control: CommonMark's terminators
        if c == "(":
            depth += 1
            if depth > _MAX_PAREN_DEPTH:
                return None
        elif c == ")":
            if depth == 0:
                break
            depth -= 1
        j += 1
    if j == i or depth:
        return None
    return j


def _scan_title(s: str, i: int, n: int) -> Optional[int]:
    """End (past the closing delimiter) of a link title starting at `i`, or None."""
    opener = s[i]
    closer = ")" if opener == "(" else opener
    j = i + 1
    while j < n:
        c = s[j]
        if c == "\\" and j + 1 < n and s[j + 1] in ASCII_PUNCTUATION:
            j += 2
            continue
        if c == closer:
            return j + 1
        if opener == "(" and c == "(":
            return None
        if c == "\n":
            k = _skip_space(s, j + 1, n, newline=False)
            if k >= n or s[k] in "\r\n":
                return None            # a blank line ends the paragraph, and the title with it
        j += 1
    return None


def _scan_commonmark(s: str, p: int, n: int) -> Optional[Tuple[int, int, bool, int]]:
    """Rung 1: `(dest_start, dest_end, angle, end past ")")` per CommonMark, or None."""
    i = _skip_space(s, p, n)
    angle = i < n and s[i] == "<"
    e = _scan_angle(s, i, n) if angle else _scan_bare(s, i, n)
    if e is None or (angle and e - i == 2):
        return None                    # no destination: nothing to check (`<>` falls to rung 3)
    j = _skip_space(s, e, n)
    if j > e and j < n and s[j] in "\"'(":
        t = _scan_title(s, j, n)
        if t is None:
            return None
        j = _skip_space(s, t, n)
    if j < n and s[j] == ")":
        return i, e, angle, j + 1
    return None


def _scan_one_line(s: str, p: int, n: int) -> Optional[Tuple[int, int, bool, int]]:
    """Rung 2: a single-line bare destination that may hold spaces, up to the balancing `)`.

    A trailing `"…"` or `'…'` title after whitespace is accepted (`[y](Foo (Bar)/ "T")`), on the
    same line and holding no `[` or `]`, so it cannot swallow a neighbouring link any more than the
    destination can. A `'` that does not open such a title is an ordinary character (`John's
    notes/`). A `(…)` title is not recognised here: in this form it cannot be told from a folder
    name, so it reads as part of the destination."""
    i = _skip_space(s, p, n, newline=False)
    depth = 0
    j = i
    while j < n:
        c = s[j]
        if c == "\\" and j + 1 < n and s[j + 1] in ASCII_PUNCTUATION:
            j += 2
            continue
        if c in "\"'" and depth == 0 and j > i and s[j - 1] in " \t":
            close = _scan_one_line_title(s, j, n)
            if close is not None:
                k = _skip_space(s, close, n, newline=False)
                if k < n and s[k] == ")":
                    e = j
                    while e > i and s[e - 1] in " \t":
                        e -= 1
                    return (i, e, False, k + 1) if e > i else None
            if c == '"':
                return None
        if c in _LOOSE_STOP or (c < " " and c != "\t") or c == "\x7f":
            return None
        if c == "(":
            depth += 1
        elif c == ")":
            if depth == 0:
                break
            depth -= 1
        j += 1
    else:
        return None
    e = j
    while e > i and s[e - 1] in " \t":
        e -= 1
    if e == i:
        return None
    return i, e, False, j + 1


def _scan_one_line_title(s: str, i: int, n: int) -> Optional[int]:
    """End (past the closing quote) of a `"…"`/`'…'` title for rung 2: one line, no `[` or `]`."""
    quote_char = s[i]
    j = i + 1
    while j < n:
        c = s[j]
        if c == "\\" and j + 1 < n and s[j + 1] in ASCII_PUNCTUATION:
            j += 2
            continue
        if c == quote_char:
            return j + 1
        if c in "\n\r[]":
            return None
        j += 1
    return None


def _scan_fallback(p: int, rparen: int) -> Optional[Tuple[int, int, bool, int]]:
    """Rung 3: the pre-scanner `[^)]+` — up to the first `)` (`rparen`, the first one at or after
    `p`), which may truncate (see above)."""
    if rparen <= p:
        return None
    return p, rparen, False, rparen + 1


def scan_links(content: str) -> Iterator[LinkMatch]:
    """Every inline Markdown link, in document order, never overlapping. Pure & deterministic.

    The same links a regex `finditer` would find: a link's text runs from its `[` to the first `]`,
    after a link the scan resumes past its `)` (a link inside another link's span is not reported),
    and a `[` that starts no link is skipped.

    Linear in the length of the content. Every rung needs a `)` to close the link, so nothing is
    tried past the last one in the file. Rung 3's `)` is found once and cached, as is the `]` that
    ends a link's text. Rung 2 stops at the next `[`, so it never crosses another link. Rung 1 can
    cross later links only while their parentheses keep it unbalanced, and a failed attempt adds a
    level each time, so `_MAX_PAREN_DEPTH` bounds how many it re-reads (the old regex was quadratic
    on input like `"[a](b" * N`)."""
    s = content
    n = len(s)
    last = s.rfind(")")                # no link can close past the last `)`
    pos = s.find("[")
    close = -1                         # the next `]` at or after the current `[`, cached
    rparen = -1                        # the next `)` at or after the current destination, cached
    while pos != -1:
        if close < pos:
            close = s.find("]", pos)
            if close == -1:
                return
        p = close + 2
        if p > last:
            return
        # Every `[` before `close` shares this same `]`, so if this one does not start a link none of
        # them does: skip to the first `[` past it. That keeps `"[" * N + "]()"` linear, where trying
        # each `[` in turn (what a regex `finditer` does) re-reads the same destination N times.
        nxt = close + 1
        if s[close + 1] == "(":
            if rparen < p:
                rparen = s.find(")", p)
            found = _scan_commonmark(s, p, n) or _scan_one_line(s, p, n) or _scan_fallback(p, rparen)
            if found is not None:
                ds, de, angle, end = found
                href = s[ds + 1:de - 1] if angle else s[ds:de]
                yield LinkMatch(pos, end, s[pos + 1:close], href, p, end - 1, ds, de, angle)
                nxt = end
        pos = s.find("[", nxt)


def destination_token(spelled: str, angle: bool) -> str:
    """The destination token for an already-spelled href: `spelled` itself, or `<spelled>`."""
    return f"<{spelled}>" if angle else spelled


def spell_destination(path: str, fragment: str, old_href: str, angle: bool) -> str:
    """The destination token for a NEW filesystem `path` (plus an already-spelled `fragment`),
    written the way the author wrote `old_href`, so `--write` changes the path and nothing else.

    * `<…>` stays `<…>`.
    * An author who percent-encoded (`%28`, `%20`, any `%XX`) gets the new path percent-encoded.
    * An author who backslash-escaped a parenthesis gets the new path's parentheses escaped.
    * An author who wrote a bare destination with a space (scanner rung 2) keeps that spelling.
    * Otherwise the path is written raw, as before.

    One change of form is made, and only when it is NECESSARY: a new path that a bare destination
    cannot hold in the author's spelling (a space where the author had none, an unbalanced
    parenthesis, a `[`) is written `<…>`. A raw space would turn a CommonMark link into plain text
    on every renderer, and darnlink must not break a link it was asked to heal. Every candidate is
    read back by the scanner before it is returned; one that does not read back as `path` is never
    written. The last resort percent-encodes the path and the fragment, which always reads back: the
    path exactly, the fragment with the same decoded value."""
    old_path = split_fragment(old_href)[0]
    frag = f"#{fragment}" if fragment else ""
    if re.search(r"%[0-9A-Fa-f]{2}", old_path):
        spelled = quote(path, safe=URL_SAFE)
    else:
        # What a URL reading would cut or decode is percent-encoded even in the raw and `<…>`
        # forms: `#` would start the fragment and `?` a query, and a `%` followed by two hex digits
        # would be decoded into another character. A folder named `C#` is written `C%23`, which
        # `destination_path` reads back as `C#`.
        spelled = re.sub(r"%(?=[0-9A-Fa-f]{2})", "%25", path).replace("#", "%23").replace("?", "%3F")
        spelled = re.sub(r"([\\<>])", r"\\\1", spelled)  # always valid: all three are punctuation
        if re.search(r"\\[()]", old_path):
            spelled = re.sub(r"([()])", r"\\\1", spelled)

    def reads_back(token: str, loose: bool) -> bool:
        # Read back with the rungs a renderer agrees with: CommonMark, and the one-line spaced form
        # only where the author already used it. Never rung 3, which "reads back" anything without a
        # `)` -- including an unbalanced `(` no renderer would show as a link.
        probe = "[](" + token + ")"
        n = len(probe)
        got = _scan_commonmark(probe, 3, n) or (_scan_one_line(probe, 3, n) if loose else None)
        if got is None or got[3] != n:
            return False
        ds, de, is_angle, _ = got
        href = probe[ds + 1:de - 1] if is_angle else probe[ds:de]
        # Judged the way every reader will: split off the fragment first, then decode the path.
        got_path, got_frag = split_fragment(href)
        return destination_path(got_path) == path and got_frag == fragment

    if not angle:
        token = spelled + frag
        if reads_back(token, loose=any(c in " \t" for c in old_path)):
            return token
    token = f"<{spelled}{frag}>"
    if reads_back(token, loose=False):
        return token
    # Nothing above reads back (a newline in a file name, or a `)` in the fragment, say). Encoding
    # the path AND the fragment always does: no space, parenthesis or control character is left.
    # The fragment keeps its `%XX` (it arrives already spelled) and its decoded value.
    if fragment:
        frag = "#" + quote(fragment, safe=URL_SAFE + "%")
    return quote(path, safe=URL_SAFE) + frag


def splice_destination(content: str, link: "LinkMatch | PlainLink | RobustLink", token: str,
                       dest_end: Optional[int] = None) -> str:
    """The text between the link's `(` and `)` with only its destination token replaced.

    `dest_end` widens the replaced span past the token (see `paren_title_as_path`)."""
    end = link.dest_end if dest_end is None else dest_end
    return content[link.inner_start:link.dest_start] + token + content[end:link.inner_end]


def paren_title_as_path(content: str, link: "LinkMatch | PlainLink | RobustLink") -> Optional[int]:
    """Where the destination would end if its `(…)` title were part of the path, or None.

    `[x](Foo (Bar))` is, in CommonMark, the destination `Foo` with the title `Bar`, and that is how
    darnlink reads it. A rewrite that kept that title would produce `[x](<Foo (Bar)/> (Bar))`, a
    folder name with a stray title glued on. Repair asks this to see whether the author meant the
    whole run (`Foo (Bar)`): the answer is the end of that run, read the way scanner rung 2 reads
    it, when it is longer than the CommonMark destination; the caller decides on the filesystem."""
    if link.angle:
        return None
    probe = content[link.inner_start:link.inner_end] + ")"
    got = _scan_one_line(probe, 0, len(probe))
    if got is None or got[3] != len(probe):
        return None
    start, end = link.inner_start + got[0], link.inner_start + got[1]
    if start != link.dest_start or end <= link.dest_end:
        return None
    return end


# A uuid comment that immediately follows a link (used to tell plain from robust).
# No `^`: it is applied with .match(content, pos), which already anchors at pos.
_TRAILING_UUID_RE = re.compile(r"\s*<!--\s*uuid:\s*(?P<uuid>[0-9a-fA-F-]{36})\s*-->")
# A pandoc attribute block immediately following a link's `)`, no whitespace allowed (pandoc's own
# rule -- a block after a space is not attached to anything and pandoc ignores it). Matched with
# .match(content, pos) the same way as _TRAILING_UUID_RE, so callers can skip past it before
# checking for the anchor comment -- see `_skip_attrs` below for why that skip has to exist at all.
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
    href: str   # as spelled: no `<…>`, no title; escapes and `%XX` kept (see `LinkMatch`)
    uuid: str
    start: int  # span of the whole robust link (link + attrs + comment) in the source
    end: int
    attrs: str = ""  # a pandoc attribute block (`{.cls}`), verbatim, or "" if there is none
    # Where the parts sit in the source (see `LinkMatch`), so a rewrite touches only the destination.
    inner_start: int = -1
    inner_end: int = -1
    dest_start: int = -1
    dest_end: int = -1
    angle: bool = False


@dataclass(frozen=True)
class PlainLink:
    text: str
    href: str   # as spelled: no `<…>`, no title; escapes and `%XX` kept (see `LinkMatch`)
    start: int  # span of just the [text](href) in the source
    end: int
    inner_start: int = -1
    inner_end: int = -1
    dest_start: int = -1
    dest_end: int = -1
    angle: bool = False


def _parts(m: LinkMatch) -> dict:
    return dict(inner_start=m.inner_start, inner_end=m.inner_end, dest_start=m.dest_start,
                dest_end=m.dest_end, angle=m.angle)


def find_robust_links(content: str, ignore: Sequence[Span] = ()) -> List[RobustLink]:
    """All robust links in the content, in document order, skipping any inside `ignore` spans.

    A robust link is a link from `scan_links` followed by an optional pandoc attribute block and
    then (any whitespace) a uuid comment -- the same test `find_plain_links` uses to leave it out,
    so the two partitions cannot disagree."""
    out: List[RobustLink] = []
    for m in scan_links(content):
        after_attrs = _skip_attrs(content, m.end)
        t = _TRAILING_UUID_RE.match(content, after_attrs)
        if t is None or _in_spans(m.start, ignore):
            continue
        out.append(RobustLink(m.text, m.href, t.group("uuid").lower(), m.start, t.end(),
                              content[m.end:after_attrs], **_parts(m)))
    return out


def find_plain_links(content: str, ignore: Sequence[Span] = ()) -> List[PlainLink]:
    """All Markdown links that are NOT already robust, skipping any inside `ignore` spans."""
    out: List[PlainLink] = []
    for m in scan_links(content):
        if _TRAILING_UUID_RE.match(content, _skip_attrs(content, m.end)):
            continue  # this link (with or without a pandoc attrs block) is already robust; skip
        if _in_spans(m.start, ignore):
            continue  # inside a generated block (e.g. autogrid); leave it alone
        out.append(PlainLink(m.text, m.href, m.start, m.end, **_parts(m)))
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
    for m in scan_links(content):
        after_attrs = _skip_attrs(content, m.end)
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

    `href` is everything that goes between `(` and `)`, verbatim: a `<…>` destination keeps its
    brackets and a title stays where it was. The write paths pass the source text there (robustify)
    or the source with only the destination token replaced (repair, `splice_destination`).

    `attrs` (a pandoc attribute block, `{.cls}`) goes immediately after `)`, with NO space -- pandoc
    only recognises the block there (FR-065). Putting the anchor comment first, as earlier versions
    did unconditionally, detaches `{.cls}` from the link it belongs to: pandoc then ignores it
    silently, and the document still renders, just without the class/width/height it was given.
    """
    return f"[{text}]({href}){attrs} <!-- uuid: {uuid} -->"
