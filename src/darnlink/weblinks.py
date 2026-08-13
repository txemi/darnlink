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


#: Exactly what `http.client` refuses to put on the wire (`_contains_disallowed_url_pchar_re`). An
#: href carrying any of these is not a URL: mirrored third-party content arrives with two truncated
#: URLs separated by a space, with control characters from OCR, with a CommonMark title glued on by
#: `MD_LINK_RE`. Matching http.client's own set rather than the narrower `\s` is deliberate — anything
#: that slips past here reaches the fetch layer and takes a different route to a different verdict for
#: the same defect.
_DISALLOWED_URL_CHARS_RE = re.compile(r"[\x00-\x20\x7f]")


@dataclass(frozen=True)
class GithubUrl:
    owner: str
    repo: str
    ref: str
    path: str  # repo-relative POSIX path to the target file

    def contents_api_url(self) -> str:
        """GitHub Contents API URL for this file. With `Accept: application/vnd.github.raw` it returns
        the raw bytes and works for BOTH public (no token) and private (token) repos — one code path.

        Every field is percent-encoded, because `http.client` encodes the request line as ASCII and
        raises `UnicodeEncodeError` on anything else: without this an ordinary accented filename killed
        the whole run. All four, not just the path — an owner or a repo can carry non-ASCII as easily.
        `safe="/%"` on the path leaves an href that is already encoded alone, so a link written with
        `%20` does not become `%2520`."""
        q = urllib.parse.quote
        return (f"https://api.github.com/repos/{q(self.owner, safe='%')}/{q(self.repo, safe='%')}"
                f"/contents/{q(self.path, safe='/%')}?ref={q(self.ref, safe='%')}")


def parse_github_url(url: str) -> Optional[GithubUrl]:
    """Pure textual parse of a GitHub blob/raw URL into (owner, repo, ref, path). No network (FR-007).
    Returns None for any unrecognised shape — the caller reports it `web_unverifiable`, never crashes.

    **An href carrying a character `http.client` would refuse is rejected outright**, which is the
    conservative half of this fix and the reason it is safe. The tempting alternative — forbid those
    characters only INSIDE the regex groups, so more links can still be resolved — silently truncates
    the path at the first offending character, fetches a DIFFERENT file, and reports its 404 as a real
    break. A false `web_not_found` in a blocking gate is worse than the crash this replaces, and worse
    than admitting the link could not be verified. Recovering the links this rejects (a CommonMark
    title glued to the href, a space inside a `#fragment`) is a separate, riskier change."""
    url = url.strip()
    if _DISALLOWED_URL_CHARS_RE.search(url):
        return None
    m = _GITHUB_BLOB_RE.match(url)
    if not m:
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
    except (http.client.InvalidURL, ValueError):
        # A URL WE built and urllib refuses to send: a darnlink defect, not the network's fault. Its
        # own sentinel, deliberately OUTSIDE `_TRANSIENT_STATUSES` — retrying a deterministic
        # client-side rejection spends real sleeps and can never succeed, and folding it into the
        # network sentinel would bury our own bug under "network error" forever. Two clauses because
        # they escape by two different doors: `InvalidURL` descends from `HTTPException`, and
        # `UnicodeEncodeError` from `ValueError`; neither is an `OSError`.
        return (-3, None)
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        # `HTTPException` covers the genuine transport failures (BadStatusLine, IncompleteRead,
        # RemoteDisconnected, …). It descends from Exception, NOT OSError, so it escaped this clause
        # entirely and propagated. Note 013 forbids that only by implication: FR-008 covers an
        # *unrecognised* URL shape, and FR-009 is worded for *transport* errors — a client-side
        # validation error is neither, so the crash fell through the gap between two requirements each
        # written assuming the other covered it.
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
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError):
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
        return WebFinding("web_unverifiable", f, link.href, "not a recognised GitHub blob/raw URL")
    if status in (401, 403):
        # NOT "private repo": this function says so itself thirteen lines down — GitHub answers 404,
        # not 403, for a private repo we cannot see. So a tokenless 403 is essentially always the
        # ANONYMOUS RATE LIMIT (60/h per public IP, shared by every machine behind the same NAT),
        # and naming it "private repo" sent readers to look for a permissions problem they did not
        # have, on destinations that were public and returned 200 to a browser.
        why = ("anonymous request rejected (403: the 60/h per-IP quota is exhausted, or the caller "
               "is blocked) — export GITHUB_TOKEN to verify" if not have_token
               else "token rejected (403/401)")
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
                          "malformed URL — the client refused to send it; nothing was fetched, and it "
                          "was not retried because a client-side rejection cannot clear on a retry")
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
