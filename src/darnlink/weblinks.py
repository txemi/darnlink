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
from .links import (MD_LINK_RE, Span, _in_spans, code_spans, ignored_spans,
                    mermaid_click_destinations)

# A web anchor is DELIBERATELY marked `web-uuid` (not the core's `uuid`): the destination uuid lives
# in ANOTHER repo, so the core's intra-repo repair/robustify — which keys on `<!-- uuid: X -->` — must
# never mistake a cross-repo web link for one of its own (FR-002). The destination repo is not recorded
# in the marker: the link's own href already names it, and a bare uuid also fits non-GitHub web links.
_TRAILING_WEB_UUID_RE = re.compile(
    r"\s*<!--\s*web-uuid:\s*(?P<uuid>[0-9a-fA-F-]{36})\s*-->"
)


#: Feature 016 (FR-011). Placement is NORMATIVE: immediately after the `)`, or immediately after a
#: `web-uuid` anchor — nowhere else. `[ \t]*`, NOT `\s*`: the latter crosses newlines, so a marker on
#: its own line — the natural way to write it for the link BELOW — silently exempted the link ABOVE,
#: suppressing a real `web_mismatch` and turning an exit 4 into a green run.
_TRAILING_OWN_EXEMPT_RE = re.compile(r"[ \t]*<!--\s*darnlink-own-exempt\s*-->")

#: FR-006. A commit SHA, long or short, in either case — GitHub accepts an uppercase SHA in `?ref=`,
#: so a rule that did not fold case would make such a link an unfixable failure. Matched WHOLE:
#: `release-deadbeef` is a branch and perfectly fixable. Purely textual, and it stops here — a TAG is
#: textually indistinguishable from a branch of the same name, and telling them apart needs the
#: network.
_IMMUTABLE_REF_RE = re.compile(r"[0-9a-fA-F]{7,40}\Z")


def owner_is_owned(owner: str, owners: frozenset) -> bool:
    """FR-001. GitHub logins are ASCII case-insensitive and the parser preserves the case it found,
    so the comparison — not the parse — folds it."""
    return owner.casefold() in owners


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
    exempt: bool = False  # FR-011: carries <!-- darnlink-own-exempt -->
    #: FR-060 -- recognised inside a diagram, where the anchor comment would be a NODE, not a
    #: comment. A property of the item and not an argument of the caller: a rule the call site
    #: must remember is a rule that disappears the day someone adds a second call site.
    report_only: bool = False


def find_mermaid_web_links(content: str, ignore: Sequence[Span] = ()) -> List[WebLink]:
    """Destinations carried by a diagram's `click` directives, in the shape the axis already
    consumes (research R3), so classification, exit codes and feature 016's own-repo rule apply
    with no special case downstream.

    `text` is empty and `end == start`: a directive has no link text and nothing may ever be
    written over it. Every item is `report_only` (FR-060)."""
    out: List[WebLink] = []
    for offset, dest in mermaid_click_destinations(content):
        if not dest.strip().lower().startswith(("http://", "https://")):
            continue  # relative destinations inside a diagram: measured zero, out of scope
        if _in_spans(offset, ignore):
            continue  # FR-058: composes with --ignore-block, like every other link
        out.append(WebLink("", dest, None, offset, offset, False, report_only=True))
    return out


def find_web_links(content: str, ignore: Sequence[Span] = (),
                   include_mermaid: bool = False,
                   block_spans: Optional[Sequence[Span]] = None) -> List[WebLink]:
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
        end = tail.end() if tail else m.end()
        uuid = tail["uuid"].lower() if tail else None
        # FR-011: recognised right after the `)` or right after the anchor, and nowhere else. `end`
        # deliberately does NOT cover it, so an exempt link that is ever rewritten keeps its marker.
        exempt = _TRAILING_OWN_EXEMPT_RE.match(content, end) is not None
        out.append(WebLink(m["text"], href, uuid, m.start(), end, exempt))
    if include_mermaid:
        if block_spans is None:
            # NOT a default of `()`. A permissive default is how the original defect got in: the
            # mermaid path silently skipped `--ignore-block` and nothing complained. A caller that
            # has no ignore-blocks says so by passing `()`; one that forgot gets this, loudly,
            # instead of a quiet regression that only shows up as a user's ignored diagram being
            # reported anyway. Same reasoning as FR-060 making `report_only` a property of the item
            # rather than something a caller must remember.
            raise ValueError(
                "find_web_links(include_mermaid=True) needs block_spans: pass the --ignore-block "
                "regions (ignored_spans(content, markers)), or () to state there are none. Do NOT "
                "pass the merged `ignore` list -- mermaid destinations live inside code spans by "
                "construction, so it would discard every one of them."
            )
        # Lifting the fence exclusion alone would find NOTHING: this scan looks for Markdown link
        # syntax, and a `click` directive is not that. The item has to be produced (research R3).
        #
        # ⚠️ `block_spans`, NOT `ignore`, and the distinction is load-bearing rather than fussy:
        # `ignore` is `--ignore-block` regions PLUS code regions, and a mermaid destination lives
        # inside a code region BY CONSTRUCTION -- filtering by the merged list would discard every
        # one of them. `block_spans` carries only what the user asked to ignore, which is what
        # FR-058 says this must compose with.
        out.extend(find_mermaid_web_links(content, block_spans))
        out.sort(key=lambda w: w.start)
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
            # `utf-8-sig`, like every LOCAL read in this package (frontmatter_edit, frontmatter_index):
            # a Windows-authored destination arrives with a BOM, plain utf-8 leaves it in front of the
            # `---`, and the frontmatter reader then sees no frontmatter at all. Before feature 016
            # that was merely an unhelpful `web_unverifiable`; with it, a destination that HAS a uuid
            # gets reported as lacking one — exit 4, over an instruction nobody can follow, because
            # adding a second `uuid:` fixes nothing. This repo already has a regression suite for the
            # same defect on the local path (tests/test_bom.py); the web path was simply left out.
            return (resp.status, resp.read().decode("utf-8-sig", errors="replace"))
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
            return False  # not readable with this token. NB 403 here is usually QUOTA (or a blocked
            # repo), not permission — a private repo answers 404. Same distinction as _classify.
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
                       # · web_own_no_uuid · web_own_exempt (feature 016)
    file: Path         # the linking file in the scanned tree
    href: str
    detail: str
    anchored_uuid: Optional[str] = None  # web_anchor: the uuid we would (or did) anchor to
    # web_unverifiable has SEVEN causes and a token fixes only two of them (401/403 and 404, both
    # WITHOUT a token). The rest — a non-GitHub URL, a destination with no uuid, a malformed URL, a
    # transport error, and anything that already failed WITH a token — are not helped by credentials.
    # Without this flag the summary told operators to "export GITHUB_TOKEN" over findings the token
    # cannot touch, including in this very repo where all 14 are non-GitHub URLs and the figure is
    # identical with and without one. An alert that fires when it cannot help is learned and ignored.
    token_would_help: bool = False


def _classify(link: WebLink, gu: Optional[GithubUrl], status: int, dest_uuid: Optional[str],
              have_token: bool, f: Path, owners: frozenset = frozenset(),
              dest_fm_status: Optional[str] = None, filtered: bool = False,
              local_root: Optional[Path] = None, own_slug: Optional[str] = None) -> WebFinding:
    """Feature 016 adds two kinds on top of 013's five. Two axes (§Precedence): visibility first —
    `--ignore-block` and code fences never reach here, and a file carrying `darnlink-ignore-file` /
    `darnlink-ignore-links` arrives with `filtered=True`, which suppresses ONLY the new finding
    (FR-014), never `web_mismatch` or `web_not_found` (FR-007). Then classification, where **status
    decides first**: anything other than 200 keeps exactly today's kind, exempt or not — a dead link
    is dead either way. The exemption and the new finding live strictly inside the 200 branch."""
    if gu is None:
        return WebFinding("web_unverifiable", f, link.href, "not a recognised GitHub blob/raw URL")
    if status in (401, 403):
        # NOT "private repo": this function says so itself thirteen lines down — GitHub answers 404,
        # not 403, for a private repo we cannot see. So a tokenless 403 is essentially always the
        # ANONYMOUS RATE LIMIT (60/h per public IP, shared by every machine behind the same NAT),
        # and naming it "private repo" sent readers to look for a permissions problem they did not
        # have, on destinations that were public and returned 200 to a browser.
        why = (f"anonymous request rejected ({status}: the 60/h per-IP quota is exhausted, or the "
               "caller is blocked) — export GITHUB_TOKEN to verify" if not have_token
               else "token rejected (403/401)")
        # token_would_help ONLY when there is no token: with one, a 401/403 means it was REJECTED,
        # and telling the operator to export the token they already exported is noise.
        return WebFinding("web_unverifiable", f, link.href, f"cannot read destination: {why}",
                          token_would_help=not have_token)
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
                              "cannot see, not necessarily moved); a token is needed to call it broken",
                              token_would_help=True)
        # PENDING-ON-DEFAULT-BRANCH, not broken. A `blob/<default-branch>/…` URL to a path that
        # EXISTS in the working tree is not a dead link: it is a link that the merge will make
        # resolve. Calling it `web_not_found` in a blocking gate creates a DEADLOCK — the red
        # blocks the merge that would fix it — and the two states are genuinely different:
        #
        #     will never resolve   -> a real break, must cut
        #     not there YET        -> resolves on merge, and cutting blocks the merge
        #
        # This repo's own doctrine already argues for it thirteen lines up in this file: *"a false
        # `web_not_found` in a blocking gate is worse than the crash this replaces"*. And it needs no
        # new kind: `web_unverifiable` is exactly the honest "cannot tell from here" bucket.
        #
        # ⚠️ TWO conditions, and the second is what makes it safe. Path-exists alone would silently
        # downgrade a REAL break whenever an unrelated repo happens to share a filename (`README.md`
        # is the obvious one). So it must also be OUR OWN repo — the only one whose working tree says
        # anything about where that URL will point after a merge.
        if (own_slug and local_root is not None
                and f"{gu.owner}/{gu.repo}".casefold() == own_slug.casefold()
                and (local_root / gu.path).exists()):
            return WebFinding("web_unverifiable", f, link.href,
                              f"destination 404s on `{gu.ref}` but `{gu.path}` EXISTS in this working "
                              "tree — pending on the default branch, not broken; it resolves when this "
                              "branch merges. Blocking here would block the merge that fixes it")
        return WebFinding("web_not_found", f, link.href,
                          "destination URL 404s; darnlink does not search where it moved (LLM layer's job)")
    if status == -3:
        return WebFinding("web_unverifiable", f, link.href,
                          "malformed URL — the client refused to send it; nothing was fetched, and it "
                          "was not retried because a client-side rejection cannot clear on a retry")
    if status != 200:
        return WebFinding("web_unverifiable", f, link.href, f"fetch failed (status {status})")
    # --- status 200 from here on ---
    if link.exempt:
        # FR-011. Exempt from FR-004, from 013's FR-005 (anchoring) and from `web_mismatch`: a
        # destination that regenerates is precisely one whose uuid drifts, so without the third the
        # hatch would not escape. Honoured with or without an owner set — it states a property of the
        # LINK, not of the run's configuration, and a marker that stopped working when someone dropped
        # `--own` would let `--write` rewrite the very files it was placed to protect.
        return WebFinding("web_own_exempt", f, link.href,
                          "carries <!-- darnlink-own-exempt -->; never anchored, never called stale")
    if link.report_only:
        # FR-060. The guard lives HERE, where the condition for writing is decided, and not in the
        # loop that happens to call this today: `web_anchor` is the only kind that produces an edit,
        # so never assigning it makes a corrupted diagram unreachable from ANY caller, present or
        # future. The destination is still watched -- 404 and mismatch were decided above, and a dead
        # link inside a drawing is exactly what this feature exists to surface.
        return WebFinding("web_ok", f, link.href,
                          "destination reachable; inside a diagram, so never anchored — a diagram "
                          "comments with %% and the anchor is an HTML comment, which would render "
                          "as a node")
    if link.uuid is None:
        # plain web link -> anchor it if the destination has a uuid
        if dest_uuid:
            return WebFinding("web_anchor", f, link.href,
                              f"plain web link; destination uuid {dest_uuid} -> would anchor",
                              anchored_uuid=dest_uuid)
        owned = gu is not None and owner_is_owned(gu.owner, owners)
        if owned and dest_fm_status == "invalid":
            # FR-004: a different defect. Telling someone to ADD a uuid to a file whose frontmatter
            # does not parse points them at the wrong thing. Gated on `owned` so FR-001 holds for the
            # message too: with the feature off this link keeps the wording it has today.
            return WebFinding("web_unverifiable", f, link.href,
                              "destination frontmatter is present but not readable (invalid YAML, or a "
                              "uuid that is not a string) — a different defect from a missing uuid")
        if (owned
                and gu.path.lower().endswith(".md")           # FR-005
                and not _IMMUTABLE_REF_RE.fullmatch(gu.ref)   # FR-006
                and not filtered):                            # FR-014
            return WebFinding("web_own_no_uuid", f, link.href,
                              f"destination is yours ({gu.owner}/{gu.repo}) and {gu.path} has no uuid "
                              f"in its frontmatter — add one there, then this link can be anchored")
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
    owners: frozenset = frozenset(),
    out_of_root: Optional[List[Path]] = None,
    include_mermaid: bool = False,
    own_slug: Optional[str] = None,
) -> Tuple[List[WebFinding], Dict[Path, str]]:
    """Fetch each web link's destination (once, cached per URL) and classify it. Returns the findings
    and the per-file rewritten content for any `web_anchor` (the caller writes it only under --write).
    Deterministic given (tree + fetcher responses). Network happens only inside `fetcher`.

    `excludes` is a set of directory-name globs to skip (same semantics as the other commands); a
    repo with vendored `clones/` of foreign repos MUST exclude them so their internal web links aren't
    fetched/anchored. Defaults to the shared `DEFAULT_EXCLUDES`."""
    from .frontmatter_index import iter_markdown_files, DEFAULT_EXCLUDES
    from .frontmatter_edit import read_text_keep_newlines
    from .links import file_ignores_links, file_is_ignored

    if excludes is None:
        excludes = DEFAULT_EXCLUDES
    have_token = bool(token)
    cache: Dict[str, Tuple[int, Optional[str]]] = {}  # href -> (status, text)
    findings: List[WebFinding] = []
    edits: Dict[Path, str] = {}

    # `out_of_root` reaches the report: this axis walks the tree on its own, so not collecting it
    # here would leave it silent exactly where nobody reads by eye -- the round-2 failure again.
    for f in iter_markdown_files(root, excludes, out_of_root=out_of_root):
        try:
            content = read_text_keep_newlines(f)
        except Exception:
            continue
        # FR-014: the file-level opt-outs suppress the NEW finding only (by kind) — a third, narrower
        # semantics than the core's "removed from the graph entirely", declared rather than left to the
        # reader. `--ignore-block` is out of this and unchanged (FR-015).
        filtered = file_is_ignored(content) or file_ignores_links(content)
        blocks = ignored_spans(content, block_markers)
        ignore = blocks + code_spans(content)
        links = find_web_links(content, ignore, include_mermaid=include_mermaid, block_spans=blocks)
        if not links:
            continue
        pieces: List[str] = []
        cursor = 0
        changed = False
        for link in links:
            gu = parse_github_url(link.href)
            if gu is None:
                findings.append(_classify(link, None, 0, None, have_token, f, owners,
                                          local_root=root, own_slug=own_slug))
                continue
            if link.href not in cache:
                cache[link.href] = fetcher(gu, token)
            status, text = cache[link.href]
            # `lstrip("\ufeff")` as well as the `utf-8-sig` decode in `_fetch_once`, and not instead of
            # it: the decode fixes the wire, this fixes the TEXT, whatever produced it. A BOM in front
            # of the `---` hides the frontmatter, and 016 turns that from an unhelpful
            # `web_unverifiable` into an exit 4 telling you to add a uuid the file already has.
            dest_fm_status, dest_uuid = (read_frontmatter_uuid(text.lstrip("\ufeff"))
                                         if (status == 200 and text is not None) else (None, None))
            fnd = _classify(link, gu, status, dest_uuid, have_token, f, owners, dest_fm_status, filtered,
                            local_root=root, own_slug=own_slug)
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
