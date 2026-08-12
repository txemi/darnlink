"""Feature 013 (EXPERIMENTAL — see specs/013-web-robustness/spec.md).

Cross-repo **web-link** robustness: anchor/verify GitHub URLs that point at a file in ANOTHER repo,
using that file's frontmatter `uuid`. Chosen design = **online-fetch, opt-in, OFF by default**.

Two layers, matching the constitution's split:
  * **Core stays offline & unchanged.** By default `darnlink`/`check`/`robustify` IGNORE web links —
    they are never treated as broken. That "ignore web by default" guard lives with this feature
    (`paths.is_web_href`, used by `repair`). Without `--online` there is zero new behaviour.
  * **`--online` opt-in.** `darnlink web-check --online` fetches the ONE destination URL (not a crawler),
    reads its `uuid`, and either ANCHORS a plain web link to it (`--write`) or VERIFIES an already-anchored
    one. It does NOT search where a moved file went (no web index exists — that is the LLM layer's job);
    a mismatch/404 is reported with an error exit.

`--online` knowingly trades Principle IV (it makes a network call) and is therefore off by default —
it is the explicit `--online` escape hatch the spike's Constitution Check named. Network happens ONLY
here. No new dependencies: `urllib` (stdlib). The fetcher is injected so tests never touch the network.
"""
from __future__ import annotations

import http.client
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .frontmatter_index import read_frontmatter_uuid
from .links import MD_LINK_RE, Span, _in_spans, code_spans, ignored_spans

# A web anchor is DELIBERATELY marked `web-uuid` (not the core's `uuid`): the destination uuid lives
# in ANOTHER repo, so the core's intra-repo repair/robustify — which keys on `<!-- uuid: X -->` — must
# never mistake a cross-repo web link for one of its own (FR-002). The destination repo is not recorded
# in the marker: the link's own href already names it, and a bare uuid also fits non-GitHub web links.
_TRAILING_WEB_UUID_RE = re.compile(
    r"\s*<!--\s*web-uuid:\s*(?P<uuid>[0-9a-fA-F-]{36})\s*-->"
)


def emit_web_anchor(text: str, href: str, uuid: str) -> str:
    """`[text](href) <!-- web-uuid: uuid -->` — the cross-repo counterpart of the core's robust link.
    `web-uuid` (not `uuid`) keeps it invisible to the core's marker (see FR-002)."""
    return f"[{text}]({href}) <!-- web-uuid: {uuid} -->"

# github.com/<owner>/<repo>/blob/<ref>/<path...>  (also tolerates /raw/ and a leading www.)
_GITHUB_BLOB_RE = re.compile(
    r"https?://(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:blob|raw)/(?P<ref>[^/]+)/(?P<path>[^#?]+)"
)


#: Exactly what `http.client` refuses to put on the wire (`_contains_disallowed_url_pchar_re`).
#: Matching its set rather than `\s` is the point: 0x7f and the C0 range passed a `\s` guard, reached the
#: fetch layer, and produced a DIFFERENT verdict for the same defect.
_DISALLOWED_URL_CHARS_RE = re.compile(r"[\x00-\x20\x7f]")

#: CommonMark link title: `[text](url "Title")`. `MD_LINK_RE` hands it to us glued to the href, so it
#: must come off before the href is judged or parsed. The `(…)` form CommonMark also allows is absent
#: on purpose: `MD_LINK_RE`'s href is `[^)]+`, so a captured href can never end in `)` and the
#: alternative would be unreachable code pretending to be coverage.
_LINK_TITLE_RE = re.compile(r"""\s+("[^"]*"|'[^']*')$""")

#: Scraped wreckage: a separator `http.client` would refuse, followed ANYWHERE LATER by a second
#: scheme. It must be caught BEFORE the regex runs, because the path group stops at the first `?` or
#: `#`: a wreckage whose first URL carries a query or a fragment parses to a TRUNCATED path, fetches a
#: different file, and reports its 404 as a hard break -- a false `web_not_found` in a blocking gate,
#: which is what this parser promises never to produce.
#:
#: An earlier version enumerated the SHAPE (whitespace, an optional quote, a scheme) and closed only
#: two of them: with a 0x7f or C0 separator, or with anything at all between the space and the scheme
#: (an angle bracket, a paren, emphasis markers, an HTML entity), the wreckage sailed through.
#: Enumerating shapes of malformed input is a losing game, so this matches the CAUSE instead -- and
#: over the same character set as the guard below, rather than the narrower one the module elsewhere
#: argues against.
_WRECKAGE_RE = re.compile(r"[\x00-\x20\x7f].*?https?://", re.IGNORECASE | re.DOTALL)


def _strip_link_title(href: str) -> str:
    """Remove a trailing CommonMark title — UNLESS its contents are themselves a URL.

    `[t]( https://…/inv... "https://…/invoker.go")` is not a titled link: it is the scraped
    two-URL wreckage this module exists to survive, wearing quotes. Stripping it would leave a
    TRUNCATED path that fetches a different file and reports its 404 as a real break — the precise
    false `web_not_found` that `parse_github_url` refuses to produce. So a "title" that starts with a
    scheme is left attached, the guards then reject the href, and the honest `web_unverifiable`
    survives.

    **Known cost, accepted deliberately.** A *legitimate* titled link whose title happens to be a URL
    (`[t](…/a.md#L10 "https://example.com/doc")`) is now unverifiable, where it used to resolve. The
    truncation argument does not apply to it — its path is already cut at the `#` — but no textual
    rule separates it from the wreckage above, and the two failure directions are not symmetric:
    unverifiable is a link this run could not confirm, while the alternative is a hard break reported
    against a file that is perfectly fine. Measured at zero occurrences across the fleet."""
    m = _LINK_TITLE_RE.search(href)
    if not m:
        return href
    if m.group(1)[1:].lstrip().lower().startswith(("http://", "https://")):
        return href
    return href[: m.start()]


@dataclass(frozen=True)
class GithubUrl:
    owner: str
    repo: str
    ref: str
    path: str  # repo-relative POSIX path to the target file

    def contents_api_url(self) -> str:
        """GitHub Contents API URL for this file. With `Accept: application/vnd.github.raw` it returns
        the raw bytes and works for BOTH public (no token) and private (token) repos — one code path.

        Path and ref are percent-encoded because `http.client` encodes the request line as ASCII and
        raises `UnicodeEncodeError` on anything else: without this a perfectly ordinary file with
        an accented filename (`documentaci%C3%B3n.md` once encoded) killed the run — the same crash
        arriving by a route that guard cannot see. `safe="/%"` leaves an already-encoded href alone,
        so a link written with `%20` does not become `%2520`. All four fields are encoded, not just
        two: an owner or repo can carry non-ASCII as easily as a path can."""
        q = lambda s, safe="%": urllib.parse.quote(s, safe=safe)  # noqa: E731
        return (f"https://api.github.com/repos/{q(self.owner)}/{q(self.repo)}"
                f"/contents/{q(self.path, '/%')}?ref={q(self.ref)}")


def parse_github_url(url: str) -> Optional[GithubUrl]:
    """Pure textual parse of a GitHub blob/raw URL into (owner, repo, ref, path). No network (FR-007).
    Returns None for any unrecognised shape — the caller reports it `web_unverifiable`, never crashes.

    A CommonMark **link title** — `[text](url "Title")` — is stripped first: `MD_LINK_RE` captures
    everything up to the closing paren, so the title arrives glued to the href. Without this, a
    perfectly ordinary titled link was unverifiable at best (and, before the guard below, a crash).

    An href carrying a CONTROL CHARACTER OR SPACE is then rejected outright, because it is not a URL.
    Mirrored third-party content (a scraped report, a ticket attachment) can carry
    `[text]( https://…/inv... https://…)`, where the "href" is really two truncated URLs with a space
    between them. Both obvious treatments end badly, and both were observed: letting it through
    reached `urllib` and raised `http.client.InvalidURL`, killing the whole run; and merely forbidding
    whitespace INSIDE the regex groups would have silently truncated the path at the space and fetched
    a DIFFERENT file, whose 404 is then reported as a real break (`web_not_found`) — a false failure,
    which is worse than saying we could not verify it. `web_unverifiable` is the honest verdict.

    The rejected set is `[\\x00-\\x20\\x7f]`, matching `http.client`'s own rule exactly rather than the
    narrower `\\s`. Scraped content carries 0x7f and C0 characters, not only spaces, and any of them
    that slips past here reaches the fetch layer and takes a different code path to a different
    verdict for the same defect.

    Two guards run, in this order, and the distinction matters:

    1. `_WRECKAGE_RE` over the **whole href** — a disallowed separator followed anywhere later by a
       second scheme. It must see the raw href, because the wreckage it detects is precisely what the
       parse would truncate.
    2. `_DISALLOWED_URL_CHARS_RE` over the **four parsed groups**, because only those go on the wire:
       `#fragment` and `?query` are dropped by the regex, so judging the raw href there made
       `…/a.md#my anchor` unverifiable over a space that is never sent."""
    url = _strip_link_title(url.strip()).strip()
    if _WRECKAGE_RE.search(url):
        return None
    m = _GITHUB_BLOB_RE.match(url)
    if not m:
        return None
    parts = (m["owner"], m["repo"], m["ref"], m["path"])
    if any(_DISALLOWED_URL_CHARS_RE.search(p) for p in parts):
        return None
    return GithubUrl(m["owner"], m["repo"], m["ref"], m["path"].rstrip("/"))


@dataclass(frozen=True)
class WebLink:
    text: str
    href: str
    uuid: Optional[str]  # None => plain web link (not yet anchored); else the anchored uuid
    start: int
    end: int


def find_web_links(content: str, ignore: Sequence[Span] = ()) -> List[WebLink]:
    """All Markdown links whose href is an http(s) URL, in document order, skipping `ignore` spans.
    A trailing `<!-- web-uuid: owner/repo#X -->` marks the link as already anchored (its uuid is captured)."""
    out: List[WebLink] = []
    for m in MD_LINK_RE.finditer(content):
        href = m["href"]
        if not href.strip().lower().startswith(("http://", "https://")):
            continue
        if _in_spans(m.start(), ignore):
            continue
        tail = _TRAILING_WEB_UUID_RE.match(content, m.end())
        if tail:
            out.append(WebLink(m["text"], href, tail["uuid"].lower(), m.start(), tail.end()))
        else:
            out.append(WebLink(m["text"], href, None, m.start(), m.end()))
    return out


# --- Fetch layer (network ONLY here; injected in tests) ---

# A fetcher maps (GithubUrl, token) -> (http_status, text_or_None).
# status: 200 ok · 404 not found · 401/403 auth-required · -1 network error · -2 repo-not-readable
# (v0.17.0: 404 whose destination repo the token cannot access -> unverifiable) · other = error.
Fetcher = Callable[[GithubUrl, Optional[str]], Tuple[int, Optional[str]]]


# Statuses that may be a TRANSIENT GitHub blip, not the destination's true state, so a retry can clear
# them. Crucially this includes 404: the Contents API returns 404 under secondary-rate-limit and for a
# file requested milliseconds after its push (CDN not yet warm) — a false `web_not_found` that would
# fail a BLOCKING gate for a link that is actually fine. 429/5xx are the usual throttle/outage codes;
# -1 is our network-error sentinel. A GENUINELY dead link stays 404 across every retry, so it is still
# reported — retry only removes the flake, never hides a real break.
_TRANSIENT_STATUSES = frozenset({404, 429, 500, 502, 503, 504, -1})


def _fetch_once(gu: GithubUrl, token: Optional[str]) -> Tuple[int, Optional[str]]:
    """One GitHub Contents API request (stdlib urllib). Sends the token when present (needed for private
    repos, harmless/higher-rate for public). Never raises: maps HTTP and network errors to a status."""
    req = urllib.request.Request(gu.contents_api_url(), headers={
        "Accept": "application/vnd.github.raw",
        "User-Agent": "darnlink-web-check",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return (resp.status, resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return (e.code, None)
    except (http.client.InvalidURL, UnicodeError):
        # A URL WE built and urllib refuses to send: a darnlink defect, not the network's fault. It
        # gets its own sentinel, deliberately OUTSIDE `_TRANSIENT_STATUSES`, for two reasons: retrying
        # a deterministic client-side rejection buys 1.5s of sleeps per malformed href and can never
        # succeed; and folding it into the network sentinel would bury our own bug under "network
        # error" forever. Every OTHER HTTPException subclass really is transport (BadStatusLine,
        # IncompleteRead, RemoteDisconnected, LineTooLong, the ImproperConnectionState family), so -1
        # is right for them.
        #
        # `UnicodeError` rides here for the same reason and is NOT redundant: `InvalidURL` does not
        # descend from it, and http.client encodes the request line as ASCII, so a non-ASCII path
        # raises UnicodeEncodeError (a ValueError) from a completely different line. Percent-encoding
        # in `contents_api_url` means neither should reach here any more — which is exactly why this
        # is a belt, kept and unit-tested rather than trusted. It is `UnicodeError`, not the whole of
        # `ValueError`: a future `ValueError` raised anywhere else inside the `try` would be labelled
        # "malformed URL", which would be a lie.
        return (-3, None)
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        # `http.client.HTTPException` is the belt to `parse_github_url`'s braces: it descends from
        # Exception, NOT from OSError, so it escaped this clause entirely and propagated — a crash.
        # Note 013 forbids that only by implication: FR-008 covers an *unrecognised* URL shape (this
        # one the regex accepted), and FR-009 covers *transport* errors (this one is client-side
        # validation). The crash fell through the gap between them.
        return (-1, None)


@lru_cache(maxsize=4096)
def _repo_accessible(owner: str, repo: str, token: Optional[str]) -> bool:
    """Is the destination REPO readable with this token? A GET on /repos/{owner}/{repo}: 200 = we can see
    it (so a 404 on a FILE inside it is a REAL break), 404/403 = we can't (a private cross-org repo, e.g.
    a client org our RO PAT has no access to) — there a file 404 is ambiguous, not a break. Cached per
    (owner, repo, token) so a repo linked N times is probed once. On a network blip, returns True
    (fall back to the plain 404=broken behaviour rather than hide a real break). Never raises."""
    url = (f"https://api.github.com/repos/{urllib.parse.quote(owner, safe='%')}"
           f"/{urllib.parse.quote(repo, safe='%')}")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "darnlink-web-check",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return False  # genuinely not readable with this token (private cross-org repo)
        return True       # 5xx/429/other: an outage/throttle, NOT inaccessible -> fall back to 404-is-broken
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, UnicodeError):
        return True   # network blip: don't downgrade a persistent 404 to unverifiable on a transient error


def default_fetcher(gu: GithubUrl, token: Optional[str], *,
                    attempts: Optional[int] = None, sleep=time.sleep) -> Tuple[int, Optional[str]]:
    """Fetch the destination file, RETRYING transient statuses with short backoff so a flaky GitHub
    response (rate-limit 404, 5xx, network blip) doesn't produce a false `web_not_found` in a blocking
    gate. A non-transient status (200/401/403, or a 404 that persists) returns immediately / after the
    last try. `attempts` (default env DARNLINK_WEB_ATTEMPTS or 3) counts the FIRST try; `sleep` is
    injectable so tests don't wait. Never raises.

    A 404 WITH a token gets one more refinement (v0.17.0): if the destination REPO is not readable with
    the token (a private cross-org repo — a client org our PAT can't see), the 404 is ambiguous, not a
    real break, so it returns the sentinel `-2` (-> `web_unverifiable`). Only a 404 in a repo we CAN read
    is called broken. This lets `web:true` run on repos that link to client/third-party orgs without a
    wall of false breaks."""
    if attempts is None:
        try:
            attempts = max(1, int(os.environ.get("DARNLINK_WEB_ATTEMPTS", "3")))
        except ValueError:
            attempts = 3
    status, text = _fetch_once(gu, token)
    for i in range(1, attempts):
        if status not in _TRANSIENT_STATUSES:
            break
        sleep(min(0.5 * (2 ** (i - 1)), 4.0))  # 0.5s, 1.0s, 2.0s, … capped at 4s
        status, text = _fetch_once(gu, token)
    if status == 404 and token and not _repo_accessible(gu.owner, gu.repo, token):
        return (-2, None)  # 404 in a repo we cannot read -> ambiguous, let _classify mark unverifiable
    return (status, text)


# --- Findings (a view over the single-URL fetch; not a new core model) ---

@dataclass(frozen=True)
class WebFinding:
    kind: str          # web_ok · web_anchor · web_mismatch · web_not_found · web_unverifiable
    file: Path         # the linking file in the scanned tree
    href: str
    detail: str
    anchored_uuid: Optional[str] = None  # web_anchor: the uuid we would (or did) anchor to


def _classify(link: WebLink, gu: Optional[GithubUrl], status: int, dest_uuid: Optional[str],
              have_token: bool, f: Path) -> WebFinding:
    if gu is None:
        # Two very different reasons land here, and the frequent one used to read as the other. A
        # scraped two-URL href IS a recognisable GitHub URL — it is simply not one we can send, and
        # telling the operator it was "not recognised" points them at the wrong thing entirely.
        if _WRECKAGE_RE.search(link.href.strip()) or _DISALLOWED_URL_CHARS_RE.search(link.href.strip()):
            return WebFinding("web_unverifiable", f, link.href,
                              "href is not sendable as a URL (whitespace or control characters — "
                              "often two truncated URLs run together in mirrored content); nothing "
                              "was fetched, and no file was guessed at")
        return WebFinding("web_unverifiable", f, link.href, "not a recognised GitHub blob/raw URL")
    if status in (401, 403):
        why = "private repo and no token provided" if not have_token else "token rejected (403/401)"
        return WebFinding("web_unverifiable", f, link.href, f"cannot read destination: {why}")
    if status == -2:
        # v0.17.0: the file 404s AND the destination repo is not readable with this token (a private
        # cross-org repo — a client org our PAT can't see). A 404 there is ambiguous (could be moved, or
        # just invisible to us), so it is NOT a break. Lets web:true run on repos linking to client orgs.
        return WebFinding("web_unverifiable", f, link.href,
                          "destination repo not readable with this token (private cross-org repo?) — its "
                          "404 is ambiguous, not necessarily moved")
    if status == 404:
        if not have_token:
            # A 404 WITHOUT a token is ambiguous: GitHub returns 404 (not 403) for a PRIVATE repo we
            # cannot see, exactly as it does for a genuinely moved/deleted file — the two are
            # indistinguishable without credentials. So a tokenless run must NOT fail on it, or every
            # dev machine / clone lacking the PAT would false-break on each private cross-repo link
            # (the real-world "35 false breaks" that block pushes). Only a TOKENED read can call a 404
            # a real break (below). This is the "fail-closed ONLY when there is a token" contract.
            return WebFinding("web_unverifiable", f, link.href,
                              "destination 404s but no token — ambiguous (could be a private repo we "
                              "cannot see, not necessarily moved); a token is needed to call it broken")
        return WebFinding("web_not_found", f, link.href,
                          "destination URL 404s; darnlink does not search where it moved (LLM layer's job)")
    if status == -3:
        return WebFinding("web_unverifiable", f, link.href,
                          "malformed URL — the client refused to send it (control character or space "
                          "in the href); nothing was fetched and it was not retried")
    if status != 200:
        return WebFinding("web_unverifiable", f, link.href, f"fetch failed (status {status})")
    # status 200: we have the destination content and its uuid (may be None)
    if link.uuid is None:
        # plain web link -> anchor it if the destination has a uuid
        if dest_uuid:
            return WebFinding("web_anchor", f, link.href,
                              f"plain web link; destination uuid {dest_uuid} -> would anchor",
                              anchored_uuid=dest_uuid)
        return WebFinding("web_unverifiable", f, link.href, "destination has no uuid to anchor to")
    # already anchored -> verify
    if dest_uuid is None:
        return WebFinding("web_mismatch", f, link.href,
                          f"link is anchored to {link.uuid} but destination has NO uuid")
    if dest_uuid == link.uuid:
        return WebFinding("web_ok", f, link.href, "anchored uuid matches destination")
    return WebFinding("web_mismatch", f, link.href,
                      f"anchored uuid {link.uuid} != destination uuid {dest_uuid}")


def check_web_links_online(
    root: Path,
    token: Optional[str] = None,
    fetcher: Fetcher = default_fetcher,
    block_markers: tuple = (),
    excludes: Optional[set] = None,
) -> Tuple[List[WebFinding], Dict[Path, str]]:
    """Fetch each web link's destination (once, cached per URL) and classify it. Returns the findings
    and the per-file rewritten content for any `web_anchor` (the caller writes it only under --write).
    Deterministic given (tree + fetcher responses). Network happens only inside `fetcher`.

    `excludes` is a set of directory-name globs to skip (same semantics as the other commands); a
    repo with vendored `clones/` of foreign repos MUST exclude them so their internal web links aren't
    fetched/anchored. Defaults to the shared `DEFAULT_EXCLUDES`."""
    from .frontmatter_index import iter_markdown_files, DEFAULT_EXCLUDES
    from .frontmatter_edit import read_text_keep_newlines

    if excludes is None:
        excludes = DEFAULT_EXCLUDES
    have_token = bool(token)
    cache: Dict[str, Tuple[int, Optional[str]]] = {}  # href -> (status, text)
    findings: List[WebFinding] = []
    edits: Dict[Path, str] = {}

    for f in iter_markdown_files(root, excludes):
        try:
            content = read_text_keep_newlines(f)
        except Exception:
            continue
        ignore = ignored_spans(content, block_markers) + code_spans(content)
        links = find_web_links(content, ignore)
        if not links:
            continue
        pieces: List[str] = []
        cursor = 0
        changed = False
        for link in links:
            gu = parse_github_url(link.href)
            if gu is None:
                findings.append(_classify(link, None, 0, None, have_token, f))
                continue
            if link.href not in cache:
                cache[link.href] = fetcher(gu, token)
            status, text = cache[link.href]
            dest_uuid = read_frontmatter_uuid(text)[1] if (status == 200 and text is not None) else None
            fnd = _classify(link, gu, status, dest_uuid, have_token, f)
            findings.append(fnd)
            if fnd.kind == "web_anchor" and fnd.anchored_uuid:
                pieces.append(content[cursor:link.start])
                pieces.append(emit_web_anchor(link.text, link.href, fnd.anchored_uuid))
                cursor = link.end
                changed = True
        if changed:
            pieces.append(content[cursor:])
            edits[f] = "".join(pieces)
    return findings, edits
