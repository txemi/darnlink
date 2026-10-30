# Feature Specification: verify web links to a declared self-hosted Forgejo

**Feature Branch**: `018-forgejo-web-links`

**Created**: 2026-09-21

**Status**: Implemented

**Input**: `web-check` recognises only `github.com` file URLs. A repository whose documentation
links into a self-hosted Forgejo (`https://forge.example.test/<owner>/<repo>/src/branch/<ref>/<path>`)
gets every such link reported `web_unverifiable`, forever: not wrong, not verified, just invisible.
A repository that MOVES its forge from GitHub to Forgejo loses the web axis for every link it
rewrites, at exactly the moment links are being rewritten in bulk.

---

## Decisions

| Question | Decision | Why |
|---|---|---|
| Detect Forgejo from the URL shape? | **No — declared only** | any server can serve that shape; fetching an arbitrary host's `/api/v1/` is not something a link checker decides alone. Undeclared: byte-for-byte today's behaviour |
| Unit of declaration | **one instance, with all its names** | the same server is typically reachable under one name on a laptop (overlay network, HTTPS) and another on a build agent (LAN, plain HTTP on a port). Declared as unrelated hosts, a link written with one name could not be verified from where only the other resolves |
| Which name is fetched | **first reachable, in declared order**; unreachable names skipped for the rest of the run | an HTTP answer of any kind is the server's answer and is final; only a network error moves on. Without the memo, an unresolvable name costs the full retry backoff on every link |
| Name syntax | **`scheme://host[:port][/prefix]`**, scheme mandatory | the same instance is often `https` on one name and `http:3000` on another; guessing the scheme verifies nothing while looking configured |
| Token | **`FORGEJO_TOKEN`**, `Authorization: token …` | never cross credentials between forges: `GITHUB_TOKEN` is never sent to a Forgejo and vice versa |
| Recognised URL forms | `src/` and `raw/` × `branch/`, `tag/`, `commit/` | `media/` serves Git LFS; the raw API would return the pointer, which has no frontmatter, turning a destination WITH a uuid into one without |
| API | `GET <name>/api/v1/repos/<owner>/<repo>/raw/<path>?ref=<ref>` | same encoding rules as the GitHub Contents API URL |

## Functional requirements

- **FR-001** With no `--forgejo`, every output is identical to the previous release.
- **FR-002** `--forgejo URL[,URL...]` is repeatable; each occurrence declares one instance.
  Malformed names (no scheme, non-http scheme, credentials, query, fragment, `github.com`, a
  name declared twice, an empty name) are a usage error (exit 1). It requires `--online`.
- **FR-003** A link on any declared name is parsed into owner, repo, ref kind, ref and path.
  Scheme and port are part of the name (default ports normalised); a sub-path install matches
  only under its prefix.
- **FR-004** Classification is shared with GitHub links: anchor, verify, mismatch, not-found with a
  token, unverifiable without one, `-2` for a 404 in a repository the token cannot read.
- **FR-005** `tag/` and `commit/` links are immutable (feature 016 FR-006), as is a branch that
  looks like a SHA.
- **FR-006** Feature 016 owners (`--own`) apply to declared Forgejo links as well.
- **FR-007** The pending-on-default-branch rung applies to a Forgejo `branch/` link only when a git
  remote of the scanned repository has its host among that instance's names and names the same
  `owner/repo`. A matching GitHub `origin` slug does NOT vouch for a repository on another forge.
- **FR-008** A `web_unverifiable` that a token would fix names the variable that would fix it.
- **FR-009** Gate recipes (bash and PowerShell) accept `forgejo_web` (list of strings), read the
  token from `DARNLINK_GATE_FORGEJO_TOKEN_FILE` (default `~/.config/forgejo_token_ro`) when the
  variable is unset, warn when there is none, and report a rejected declaration as configuration.

## Out of scope

- Branch names containing `/` **on GitHub** (the parser takes the first segment as the ref). On a
  declared Forgejo this was lifted after 0.28.0: a 404 is asked again with the ref lengthened one
  path segment at a time, up to four (CHANGELOG, Unreleased).
- Forgejo's legacy ref-kind-less form `/<owner>/<repo>/src/<ref>/<path>`.
- Per-instance tokens.

## Tests

`tests/test_forgejo_web_links.py` (hosts under `example.test`, network never touched) and the
`forgejo_web` wiring tests in `tests/test_recipe_gate.py`. Each was checked by mutation: token
routing, the unreachable-name memo, the branch-only and identity conditions of the pending rung,
immutability, the auth scheme, the `-2` sentinel, `media/` exclusion, and the recipe wiring.
