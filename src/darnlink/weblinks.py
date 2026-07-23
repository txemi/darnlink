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

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
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


@dataclass(frozen=True)
class GithubUrl:
    owner: str
    repo: str
    ref: str
    path: str  # repo-relative POSIX path to the target file

    def contents_api_url(self) -> str:
        """GitHub Contents API URL for this file. With `Accept: application/vnd.github.raw` it returns
        the raw bytes and works for BOTH public (no token) and private (token) repos — one code path."""
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/contents/{self.path}?ref={self.ref}"


def parse_github_url(url: str) -> Optional[GithubUrl]:
    """Pure textual parse of a GitHub blob/raw URL into (owner, repo, ref, path). No network (FR-007).
    Returns None for any unrecognised shape — the caller reports it `web_unverifiable`, never crashes."""
    m = _GITHUB_BLOB_RE.match(url.strip())
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
# status: 200 ok · 404 not found · 401/403 auth-required · -1 network error · other = error.
Fetcher = Callable[[GithubUrl, Optional[str]], Tuple[int, Optional[str]]]


def default_fetcher(gu: GithubUrl, token: Optional[str]) -> Tuple[int, Optional[str]]:
    """Fetch the single destination file via the GitHub Contents API (stdlib urllib). Sends the token
    when present (needed for private repos, harmless/higher-rate for public). Never raises: maps HTTP
    and network errors to a status code."""
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
    except (urllib.error.URLError, TimeoutError, OSError):
        return (-1, None)


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
        why = "private repo and no GITHUB_TOKEN in env" if not have_token else "token rejected (403/401)"
        return WebFinding("web_unverifiable", f, link.href, f"cannot read destination: {why}")
    if status == 404:
        return WebFinding("web_not_found", f, link.href,
                          "destination URL 404s; darnlink does not search where it moved (LLM layer's job)")
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
