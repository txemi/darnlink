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
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .frontmatter_index import read_frontmatter_uuid
from .paths import resolved
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

#: The GitHub REST API. One constant rather than a literal per call site: it is also the ONLY origin
#: a GITHUB_TOKEN may be sent to, including after a redirect (`_github_open`).
_GITHUB_API = "https://api.github.com"

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
class ForgejoServer:
    """One self-hosted Forgejo instance a consuming repo DECLARED, under every name it answers to.

    A single server routinely has several names, and which of them resolves depends on where the
    run happens: a name on a private overlay network works on a laptop and not on a build agent,
    a LAN name the other way round. Links are recognised under ANY of the names; the fetch tries
    them in declared order and moves on only when a name is unreachable (see `_fetch_forgejo`).
    Declaring the names as ONE server, rather than as unrelated hosts, is what lets a link written
    with one name be verified through another, and what lets the pending-on-default-branch rung
    recognise this repo under all of them.

    Each base is normalised `scheme://host[:port][/prefix]` — lowercase scheme and host, default
    port dropped, no trailing slash. The prefix is for an instance served under a sub-path.
    """
    bases: Tuple[str, ...]

    @property
    def key(self) -> str:
        """Identity of the server: its FIRST declared name. Stable for a given configuration."""
        return self.bases[0]

    def hostnames(self) -> frozenset:
        return frozenset(urllib.parse.urlsplit(b).hostname or "" for b in self.bases)


def _normalise_base(name: str) -> str:
    """One declared name -> normalised base. Raises ValueError with a message meant for a human
    reading a usage error: this is configuration, and a silently-dropped name would verify less
    than the configuration claims — the false green every gate in this project is built against."""
    raw = name.strip()
    if not raw:
        raise ValueError("an empty Forgejo name declares nothing")
    if not raw.isascii() or _DISALLOWED_URL_CHARS_RE.search(raw):
        raise ValueError(f"{raw!r}: not an ASCII URL without spaces or control characters")
    try:
        sp = urllib.parse.urlsplit(raw)
        port = sp.port
    except ValueError as e:
        raise ValueError(f"{raw!r}: {e}") from None
    if sp.scheme.lower() not in ("http", "https") or not sp.hostname:
        # A bare host is refused, not completed with a guessed scheme: the same instance is often
        # plain http on one name (a LAN port) and https on another, and guessing wrong verifies
        # nothing while looking configured.
        raise ValueError(f"{raw!r}: needs an explicit http:// or https:// scheme and a host")
    if sp.username is not None or sp.password is not None:
        raise ValueError(f"{raw!r}: credentials do not belong in a declared name (use FORGEJO_TOKEN)")
    if sp.query or sp.fragment:
        raise ValueError(f"{raw!r}: a base URL carries no query or fragment")
    host = sp.hostname.lower()
    if host in ("github.com", "www.github.com"):
        raise ValueError(f"{raw!r}: github.com is recognised natively; it is not a Forgejo instance")
    scheme = sp.scheme.lower()
    default_port = {"http": 80, "https": 443}[scheme]
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    return f"{scheme}://{netloc}{sp.path.rstrip('/')}"


def parse_forgejo_servers(specs: Sequence[str]) -> Tuple[ForgejoServer, ...]:
    """`--forgejo` values -> servers. Each spec is ONE server; its names are comma-separated.
    A name declared twice (in one server or across two) is an error: it would make a link's server
    depend on declaration order, which is a decision nobody wrote down."""
    servers: List[ForgejoServer] = []
    seen: Dict[str, str] = {}
    for spec in specs:
        bases: List[str] = []
        for name in spec.split(","):
            base = _normalise_base(name)
            if base in seen:
                raise ValueError(f"{base} is declared twice (also in {seen[base]!r})")
            seen[base] = spec
            bases.append(base)
        servers.append(ForgejoServer(tuple(bases)))
    return tuple(servers)


# <owner>/<repo>/(src|raw)/(branch|tag|commit)/<ref>/<path...>, relative to a declared base. `media/`
# is deliberately NOT recognised: it serves Git LFS objects, and the raw API would hand back the LFS
# pointer — a text with no frontmatter — so a destination with a uuid would read as one without.
_FORGEJO_FILE_RE = re.compile(
    r"/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:src|raw)/(?P<kind>branch|tag|commit)/(?P<ref>[^/]+)"
    r"/(?P<path>[^#?]+)"
)


@dataclass(frozen=True)
class GithubUrl:
    """A parsed link to ONE FILE in a forge: GitHub (the default) or a declared Forgejo instance.

    The name predates Forgejo support and is kept because it is part of the fetcher contract
    (`Fetcher` receives one); `forge is None` means github.com, exactly as before."""
    owner: str
    repo: str
    ref: str
    path: str  # repo-relative POSIX path to the target file
    #: None = github.com. Otherwise the declared Forgejo server the link was written against.
    forge: Optional[ForgejoServer] = None
    #: Forgejo only: `branch`, `tag` or `commit` — the URL says which, unlike GitHub's.
    ref_kind: str = ""

    @property
    def token_var(self) -> str:
        """The environment variable whose token belongs to this destination. Two variables, never
        one: sending a GitHub token to a self-hosted server — or the other way round — hands a
        credential to a host it was never issued for."""
        return "FORGEJO_TOKEN" if self.forge is not None else "GITHUB_TOKEN"

    def is_immutable_ref(self) -> bool:
        """FR-006: a link that can never be fixed. On Forgejo the URL states it — `tag/` and
        `commit/` — and a SHA-looking branch is judged exactly as on GitHub."""
        if self.forge is not None and self.ref_kind in ("tag", "commit"):
            return True
        return _IMMUTABLE_REF_RE.fullmatch(self.ref) is not None

    def raw_api_url(self, base: str) -> str:
        """Forgejo raw-file API through ONE of the server's names:
        `<base>/api/v1/repos/<owner>/<repo>/raw/<path>?ref=<ref>`. Encoded exactly like
        `contents_api_url`, for the same reason."""
        q = urllib.parse.quote
        return (f"{base}/api/v1/repos/{q(self.owner, safe='%')}/{q(self.repo, safe='%')}"
                f"/raw/{q(self.path, safe='/%')}?ref={q(self.ref, safe='%')}")

    def contents_api_url(self) -> str:
        """GitHub Contents API URL for this file. With `Accept: application/vnd.github.raw` it returns
        the raw bytes and works for BOTH public (no token) and private (token) repos — one code path.

        Every field is percent-encoded, because `http.client` encodes the request line as ASCII and
        raises `UnicodeEncodeError` on anything else: without this an ordinary accented filename killed
        the whole run. All four, not just the path — an owner or a repo can carry non-ASCII as easily.
        `safe="/%"` on the path leaves an href that is already encoded alone, so a link written with
        `%20` does not become `%2520`."""
        q = urllib.parse.quote
        return (f"{_GITHUB_API}/repos/{q(self.owner, safe='%')}/{q(self.repo, safe='%')}"
                f"/contents/{q(self.path, safe='/%')}?ref={q(self.ref, safe='%')}")


def parse_github_url(url: str, forgejo: Sequence[ForgejoServer] = ()) -> Optional[GithubUrl]:
    """Pure textual parse of a GitHub blob/raw URL into (owner, repo, ref, path). No network (FR-007).
    Returns None for any unrecognised shape — the caller reports it `web_unverifiable`, never crashes.

    With `forgejo` servers declared, a file URL on one of their names is recognised too (the shape
    `/<owner>/<repo>/src|raw/branch|tag|commit/<ref>/<path>`). Without them nothing changes: a
    self-hosted forge is never GUESSED from a URL's shape, because any server can serve that shape
    and fetching an arbitrary host's `/api/v1/` is not something a link checker should decide alone.

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
    if m:
        return GithubUrl(m["owner"], m["repo"], m["ref"], m["path"].rstrip("/"))
    return _parse_forgejo_url(url, forgejo) if forgejo else None


def _parse_forgejo_url(url: str, servers: Sequence[ForgejoServer]) -> Optional[GithubUrl]:
    """Match `url` against the declared names. Scheme and port are part of the name: a link written
    `http://` to a name declared `https://` is a different origin and is not recognised."""
    if not url.isascii():
        return None  # declared names are ASCII; a lookalike host must not casefold its way in
    try:
        sp = urllib.parse.urlsplit(url)
        port = sp.port
    except ValueError:
        return None
    scheme = sp.scheme.lower()
    if scheme not in ("http", "https") or not sp.hostname or sp.username is not None:
        return None
    default_port = {"http": 80, "https": 443}[scheme]
    netloc = sp.hostname.lower() if port in (None, default_port) else f"{sp.hostname.lower()}:{port}"
    origin = f"{scheme}://{netloc}"
    # Every declared name on this origin, MOST SPECIFIC PREFIX FIRST, across all servers. Declaration
    # order must not decide: with `https://h` and `https://h/sub` both declared, the root name always
    # matches `/sub/o/r/…` as a path, so trying it first read `sub` as the owner and gave up on a link
    # the sub-path name recognises.
    candidates = []
    for server in servers:
        for base in server.bases:
            if not base.startswith(origin):
                continue
            # What follows the origin in the base: "" or a sub-path. When the origin is only a
            # STRING prefix of the base's (`https://h` against a base `https://h:3000`) this is
            # `:3000`, and no URL path — which always starts with `/` — can start with it.
            prefix = base[len(origin):]
            if sp.path == prefix or sp.path.startswith(prefix + "/"):
                candidates.append((len(prefix), server, prefix))
    for _, server, prefix in sorted(candidates, key=lambda c: -c[0]):
        m = _FORGEJO_FILE_RE.fullmatch(sp.path[len(prefix):])
        if m:
            return GithubUrl(m["owner"], m["repo"], m["ref"], m["path"].rstrip("/"),
                             forge=server, ref_kind=m["kind"])
    return None  # no declared name sees a link to a file here: nothing to verify


def forgejo_identity_of_remote(url: str, servers: Sequence[ForgejoServer]
                               ) -> Optional[Tuple[str, str]]:
    """A git remote URL -> (server key, `owner/repo` lowercased) when it points at a declared
    Forgejo server, else None. Matched on the HOST only: a remote is usually SSH on its own port
    while the declared names are the web origin, so scheme and port cannot be required to agree.
    Accepts `scheme://[user@]host[:port]/…/owner/repo[.git]` and scp-like `[user@]host:owner/repo`."""
    m = re.match(r"(?:[a-z][a-z0-9+.-]*://(?:[^/@]*@)?(?P<h1>[^/:]+)(?::\d+)?/(?P<p1>.+)"
                 r"|(?:[^/@]*@)?(?P<h2>[^/:]+):(?P<p2>.+))\Z", url.strip(), re.IGNORECASE | re.ASCII)
    if not m:
        return None
    host = (m["h1"] or m["h2"]).lower()
    path = (m["p1"] or m["p2"]).rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return None
    for server in servers:
        if host in server.hostnames():
            return (server.key, f"{parts[-2]}/{parts[-1]}".lower())
    return None


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


def _origin_of(url: str) -> Optional[str]:
    """`scheme://host[:port]`, normalised exactly like a declared name (default port dropped)."""
    try:
        sp = urllib.parse.urlsplit(url)
        port = sp.port
    except ValueError:
        return None
    scheme = sp.scheme.lower()
    if scheme not in ("http", "https") or not sp.hostname:
        return None
    default_port = {"http": 80, "https": 443}[scheme]
    host = sp.hostname.lower()
    return f"{scheme}://{host}" if port in (None, default_port) else f"{scheme}://{host}:{port}"


class _ScopedAuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but keep `Authorization` ONLY while the target is one of the server's
    declared names. urllib's own handler copies every non-content header onto the redirected
    request — measured: a 302 from a declared name to another host:port delivered the token there,
    breaking the one promise this feature makes about credentials."""

    def __init__(self, allowed_origins: frozenset):
        super().__init__()
        self.allowed_origins = allowed_origins

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and _origin_of(newurl) not in self.allowed_origins:
            new.remove_header("Authorization")
        return new


def _scoped_open(allowed_origins: frozenset, req: "urllib.request.Request", timeout: int):
    """`urlopen`, except that a request carrying `Authorization` follows redirects through
    `_ScopedAuthRedirectHandler`, so the credential never leaves `allowed_origins`. A request with
    no credential has nothing to leak and goes through plain `urlopen`."""
    if not req.has_header("Authorization"):
        return urllib.request.urlopen(req, timeout=timeout)
    return urllib.request.build_opener(_ScopedAuthRedirectHandler(allowed_origins)).open(
        req, timeout=timeout)


def _forgejo_open(server: ForgejoServer, req: "urllib.request.Request", timeout: int):
    """`urlopen` for a declared Forgejo: redirects may not carry the token off its names."""
    return _scoped_open(frozenset(o for o in (_origin_of(b) for b in server.bases) if o), req, timeout)


def _github_open(req: "urllib.request.Request", timeout: int):
    """`urlopen` for the GitHub API: redirects may not carry GITHUB_TOKEN off `_GITHUB_API`. The API
    does redirect (a renamed repository answers 301 to its new location on the same host), and
    urllib would otherwise copy the header onto a redirect to ANY host."""
    return _scoped_open(frozenset({_origin_of(_GITHUB_API)}), req, timeout)


def _fetch_once(gu: GithubUrl, token: Optional[str],
                base: Optional[str] = None) -> Tuple[int, Optional[str]]:
    """One API request for the destination file (stdlib urllib). Sends the token when present (needed
    for private repos, harmless/higher-rate for public). Never raises: maps HTTP and network errors to
    a status. GitHub: the Contents API. A declared Forgejo: its raw API through `base`, one of the
    server's names (the first when not given), with Forgejo's `token` authorization scheme."""
    if gu.forge is None:
        req = urllib.request.Request(gu.contents_api_url(), headers={
            "Accept": "application/vnd.github.raw",
            "User-Agent": "darnlink-web-check",
        })
        if token:
            req.add_header("Authorization", f"Bearer {token}")
    else:
        req = urllib.request.Request(gu.raw_api_url(base or gu.forge.key), headers={
            "User-Agent": "darnlink-web-check",
        })
        if token:
            req.add_header("Authorization", f"token {token}")
    try:
        opened = (_github_open(req, 15) if gu.forge is None
                  else _forgejo_open(gu.forge, req, 15))
        with opened as resp:
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
    url = (f"{_GITHUB_API}/repos/{urllib.parse.quote(owner, safe='%')}"
           f"/{urllib.parse.quote(repo, safe='%')}")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "darnlink-web-check",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with _github_open(req, 15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return False  # not readable with this token. NB 403 here is usually QUOTA (or a blocked
            # repo), not permission — a private repo answers 404. Same distinction as _classify.
        return True       # 5xx/429/other: an outage/throttle, NOT inaccessible -> fall back to 404-is-broken
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError):
        return True   # network blip: don't downgrade a persistent 404 to unverifiable on a transient error


@lru_cache(maxsize=4096)
def _forgejo_repo_accessible(server: ForgejoServer, base: str, owner: str, repo: str,
                             token: Optional[str]) -> bool:
    """`_repo_accessible` for a declared Forgejo, through one of its names. Forgejo, like GitHub,
    answers 404 for a private repository the caller cannot see. Same fallbacks, same reasons."""
    q = urllib.parse.quote
    req = urllib.request.Request(f"{base}/api/v1/repos/{q(owner, safe='%')}/{q(repo, safe='%')}",
                                 headers={"Accept": "application/json",
                                          "User-Agent": "darnlink-web-check"})
    if token:
        req.add_header("Authorization", f"token {token}")
    try:
        with _forgejo_open(server, req, 15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        return e.code not in (403, 404)
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError):
        return True


#: Names of declared Forgejo servers that were UNREACHABLE (network error after every retry) in
#: this process. Without it, a name that does not resolve where the run happens — the normal case
#: for one of a server's names — would cost the full retry backoff on EVERY link before falling
#: through to the name that works. Only the network sentinel lands here: an HTTP answer of any kind
#: proves the name reaches the server. `_forgejo_unreachable.clear()` resets it (tests do).
_forgejo_unreachable: set = set()


def _default_attempts() -> int:
    try:
        return max(1, int(os.environ.get("DARNLINK_WEB_ATTEMPTS", "3")))
    except ValueError:
        return 3


def _with_retries(call: Callable[[], Tuple[int, Optional[str]]], attempts: int,
                  sleep) -> Tuple[int, Optional[str]]:
    status, text = call()
    for i in range(1, attempts):
        if status not in _TRANSIENT_STATUSES:
            break
        sleep(min(0.5 * (2 ** (i - 1)), 4.0))  # 0.5s, 1.0s, 2.0s, … capped at 4s
        status, text = call()
    return status, text


#: How many path segments a slashed branch or tag name may borrow (`release/2026/q4` borrows two).
#: A bound, because each extra split costs one request on a link that is probably just broken.
_MAX_REF_SLASHES = 4


def _longer_refs(gu: GithubUrl):
    """The other readings of a `branch/` or `tag/` link whose ref contains a slash. The URL cannot
    say where the ref ends — `raw/branch/informes/datos/x.html` is ref `informes` + path
    `datos/x.html` OR ref `informes/datos` + path `x.html`; Forgejo resolves it by looking the name
    up, and the parse (`[^/]+`) only ever takes the first segment. A `commit/` ref is a SHA and never
    holds a slash, so it has no other reading."""
    if gu.ref_kind not in ("branch", "tag"):
        return
    parts = gu.path.split("/")
    for i in range(1, min(len(parts), _MAX_REF_SLASHES + 1)):
        yield replace(gu, ref=f"{gu.ref}/{'/'.join(parts[:i])}", path="/".join(parts[i:]))


def _fetch_forgejo(gu: GithubUrl, token: Optional[str], attempts: int,
                   sleep) -> Tuple[int, Optional[str]]:
    """Try the server's names in declared order; the first that ANSWERS decides. A name that only
    yields network errors is skipped — and remembered as unreachable for the rest of the run.
    A 404 on a reachable name is never retried through another name: it is the server's answer,
    and the other names are the same server. It IS retried, on that same name, with the ref
    lengthened one segment at a time (`_longer_refs`): a branch named `informes/datos` otherwise
    reads as a false `web_not_found` on every file it holds."""
    assert gu.forge is not None
    for base in gu.forge.bases:
        if base in _forgejo_unreachable:
            continue
        status, text = _with_retries(lambda: _fetch_once(gu, token, base), attempts, sleep)
        if status == -1:
            _forgejo_unreachable.add(base)
            continue
        if status == 404:
            for alt in _longer_refs(gu):
                # One try each, no retries: 404 counts as transient in `_with_retries`, and these
                # readings are expected to 404 — retrying them would sleep through every broken link.
                alt_status, alt_text = _fetch_once(alt, token, base)
                if alt_status != 404:
                    return (alt_status, alt_text)
        if status == 404 and token and not _forgejo_repo_accessible(gu.forge, base, gu.owner, gu.repo, token):
            return (-2, None)
        return (status, text)
    return (-1, None)


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
        attempts = _default_attempts()
    if gu.forge is not None:
        return _fetch_forgejo(gu, token, attempts, sleep)
    status, text = _with_retries(lambda: _fetch_once(gu, token), attempts, sleep)
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
    #: Which variable would help when `token_would_help`: GitHub and a declared Forgejo take
    #: DIFFERENT tokens, and advice naming the wrong one cannot be followed.
    token_var: str = "GITHUB_TOKEN"


@dataclass(frozen=True)
class OwnRepo:
    """What we must know about the repo WE ARE IN to be able to say "pending, not broken".

    The three facts travel together rather than loose because all three must come from the SAME
    reading of git: mixing one repo's slug with another's toplevel IS one of the leaks an
    adversarial review walked through — the gate supports scanning a SUBDIRECTORY, and there `root`
    stops being the repo root while `<path>` stays relative to it.
    """
    slug: str          # owner/repo of `origin` on GitHub; "" when `origin` is not on GitHub
    root: Path         # `git rev-parse --show-toplevel`, NOT the scanned directory
    default_ref: str   # the default branch of `origin`, e.g. `main` or `master`
    #: (server key, `owner/repo` lowercased) for every remote on a DECLARED Forgejo server — how
    #: this same repository is named there. Empty when no server is declared.
    forgejo_slugs: frozenset = frozenset()


def _pendiente_en_la_rama_por_defecto(gu: "GithubUrl", own: Optional["OwnRepo"]) -> bool:
    """Is this 404 "not published yet" rather than "broken"? Only if ALL of the following hold.

    Each condition closes a leak MEASURED in adversarial review. An earlier draft checked only two
    — own repo, and `.exists()` — and every case below walked through it GREEN while being a link
    that no merge will ever resolve. A gate that lets a real break past is worse than one that cuts
    too much: green reads the same whether it is right or blind.
    """
    if own is None:
        return False
    # (1) ASCII SLUG, and `.lower()` rather than `.casefold()`. GitHub slugs are ASCII, so any URL
    #     carrying anything else is a permanently dead link — and `casefold()` COLLAPSES exactly
    #     those lookalikes: U+212A (KELVIN) folds to `k`, U+00DF to `ss`. The sibling helper
    #     `_github_owner_from_origin` carries an explicit comment about `re.ASCII` and U+0131 for
    #     this same reason; this comparison did not inherit that hardening.
    if not (gu.owner.isascii() and gu.repo.isascii()):
        return False
    if gu.forge is None:
        if f"{gu.owner}/{gu.repo}".lower() != own.slug.lower():
            return False
    else:
        # A declared Forgejo is this repo only when one of its REMOTES lives there under this slug
        # (`OwnRepo.forgejo_slugs`) — never merely because the slug matches the GitHub one: the same
        # `owner/repo` on two forges can be two different repositories. And only a `branch/` link
        # can be pending: `tag/` and `commit/` say in the URL that nothing will move them.
        if gu.ref_kind != "branch":
            return False
        if (gu.forge.key, f"{gu.owner}/{gu.repo}".lower()) not in own.forgejo_slugs:
            return False
    # (2) THE REF MUST BE THE DEFAULT BRANCH. It is what the message claims ("resolves when this
    #     branch merges") and what went unchecked: a `blob/<sha>/x` or `blob/v1.0.0/x` is IMMUTABLE
    #     — it will never resolve — and was forgiven all the same. This file already ships the
    #     detector (`_IMMUTABLE_REF_RE`, used for exactly this in FR-006); requiring the default
    #     branch is stronger still and does not depend on guessing what an immutable ref looks like.
    if not own.default_ref or gu.ref != own.default_ref:
        return False
    # (3) THE PATH, CONFINED TO THE TREE. URL paths are PERCENT-ENCODED, and this matters daily
    #     here: folder names carry a timezone offset (`…T104500+0200_…`), which in a URL is `%2B`.
    #     Undecoded, the rung sat silently inert on the commonest shape in the repo — it did not
    #     fail, it did nothing. And `Path(root) / "/etc/hostname"` IS `/etc/hostname` on POSIX, so
    #     an absolute path left the repo entirely and `.exists()` happily agreed.
    ruta = unquote(gu.path)
    if ruta.startswith("/") or ".." in PurePosixPath(ruta).parts:
        return False
    destino = own.root / ruta
    try:
        if not resolved(destino).is_relative_to(resolved(own.root)):
            return False
    except (OSError, ValueError):
        return False
    # (4) AND IT MUST BE A TRACKED FILE. `.exists()` accepts a DIRECTORY (which GitHub serves under
    #     `/tree/`, so `/blob/<dir>` 404s forever) and a GITIGNORED file, which no merge puts on the
    #     default branch. Neither of them is fixed by merging.
    if not destino.is_file():
        return False
    return _esta_versionado(own.root, ruta)


def _esta_versionado(root: "Path", ruta: str) -> bool:
    """`git ls-files --error-unmatch`. Fail-closed: on any doubt, do NOT forgive."""
    import os as _os
    import subprocess
    env = {k: v for k, v in _os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", ruta],
                           capture_output=True, text=True, timeout=10, env=env)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _classify(link: WebLink, gu: Optional[GithubUrl], status: int, dest_uuid: Optional[str],
              have_token: bool, f: Path, owners: frozenset = frozenset(),
              dest_fm_status: Optional[str] = None, filtered: bool = False,
              own: Optional["OwnRepo"] = None) -> WebFinding:
    """Feature 016 adds two kinds on top of 013's five. Two axes (§Precedence): visibility first —
    `--ignore-block` and code fences never reach here, and a file carrying `darnlink-ignore-file` /
    `darnlink-ignore-links` arrives with `filtered=True`, which suppresses ONLY the new finding
    (FR-014), never `web_mismatch` or `web_not_found` (FR-007). Then classification, where **status
    decides first**: anything other than 200 keeps exactly today's kind, exempt or not — a dead link
    is dead either way. The exemption and the new finding live strictly inside the 200 branch."""
    if gu is None:
        return WebFinding("web_unverifiable", f, link.href, "not a recognised GitHub blob/raw URL")
    if gu.forge is not None and status in (401, 403):
        # A self-hosted server has no anonymous 60/h quota story to tell: a rejection is about
        # credentials, and the variable to set is Forgejo's own.
        why = (f"anonymous request rejected ({status}) — export FORGEJO_TOKEN to verify"
               if not have_token else f"token rejected ({status})")
        return WebFinding("web_unverifiable", f, link.href, f"cannot read destination: {why}",
                          token_would_help=not have_token, token_var=gu.token_var)
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
                              token_would_help=True, token_var=gu.token_var)
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
        if _pendiente_en_la_rama_por_defecto(gu, own):
            return WebFinding("web_unverifiable", f, link.href,
                              f"destination 404s on the default branch `{gu.ref}` but `{gu.path}` is a "
                              "TRACKED FILE in this working tree — pending on the default branch, not "
                              "broken. It resolves when this branch merges (or stays pending if the "
                              "branch is abandoned); blocking here would block that merge")
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
                and not gu.is_immutable_ref()                 # FR-006
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
    own: Optional["OwnRepo"] = None,
    forgejo: Sequence[ForgejoServer] = (),
    forgejo_token: Optional[str] = None,
) -> Tuple[List[WebFinding], Dict[Path, str]]:
    """Fetch each web link's destination (once, cached per URL) and classify it. Returns the findings
    and the per-file rewritten content for any `web_anchor` (the caller writes it only under --write).
    Deterministic given (tree + fetcher responses). Network happens only inside `fetcher`.

    `excludes` is a set of directory-name globs to skip (same semantics as the other commands); a
    repo with vendored `clones/` of foreign repos MUST exclude them so their internal web links aren't
    fetched/anchored. Defaults to the shared `DEFAULT_EXCLUDES`.

    `forgejo` declares self-hosted Forgejo servers whose file links are verified like GitHub's;
    their destinations are fetched with `forgejo_token`, never with the GitHub `token`."""
    from .frontmatter_index import iter_markdown_files, DEFAULT_EXCLUDES
    from .frontmatter_edit import read_text_keep_newlines
    from .links import file_ignores_links, file_is_ignored

    if excludes is None:
        excludes = DEFAULT_EXCLUDES
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
            gu = parse_github_url(link.href, forgejo)
            if gu is None:
                findings.append(_classify(link, None, 0, None, bool(token), f, owners,
                                          own=own))
                continue
            link_token = forgejo_token if gu.forge is not None else token
            have_token = bool(link_token)
            if link.href not in cache:
                cache[link.href] = fetcher(gu, link_token)
            status, text = cache[link.href]
            # `lstrip("\ufeff")` as well as the `utf-8-sig` decode in `_fetch_once`, and not instead of
            # it: the decode fixes the wire, this fixes the TEXT, whatever produced it. A BOM in front
            # of the `---` hides the frontmatter, and 016 turns that from an unhelpful
            # `web_unverifiable` into an exit 4 telling you to add a uuid the file already has.
            dest_fm_status, dest_uuid = (read_frontmatter_uuid(text.lstrip("\ufeff"))
                                         if (status == 200 and text is not None) else (None, None))
            fnd = _classify(link, gu, status, dest_uuid, have_token, f, owners, dest_fm_status, filtered,
                            own=own)
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
