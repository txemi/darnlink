# Feature Specification: web-link robustness (cross-repo URL links anchored to a target's `uuid`)

**Feature Branch**: `darnlink-web` (long-lived product line — integrates `main`, **never merges back to `main` as-is**)

**Created**: 2026-07-17

**Status**: **Spike / EXPERIMENTAL.** Design **decided by txemi**: the chosen path is **online-fetch,
opt-in, OFF by default** (see §Decision). This spec measures whether the feature is worth doing and what
it costs the constitution. **Do not merge to `main`.**

**Input**: Today darnlink only heals **local, relative** Markdown links (`is_local_md` rejects any
`http(s)://`). A downstream setup (a Jenkins pipeline splitting living docs across **two repos**,
`txnet1` and `txconta`) wires them together with **GitHub URLs**: a file in `txconta` links to a file
in `txnet1` by its `https://github.com/txemi/txnet1/blob/main/…/jenkins_topologia.md` URL. When the
target is renamed/moved inside `txnet1`, that URL 404s and darnlink cannot help — the target's `uuid`
lives in *another repository*, which darnlink, by design, never looks at. The ask: make those
**cross-repo web links** robust too, anchored to the destination file's `uuid`.

The motivating link (the real case the prototype exercises):

```
Ver la [topología Jenkins](https://github.com/txemi/txnet1/blob/main/projects/software/homelab/docs_vivos/jenkins_topologia.md) <!-- uuid: 3f9c… -->
```

lives in `txconta/.../jenkins_topologia.md` and points at `txnet1/.../docs_vivos/jenkins_topologia.md`.

---

## The nub (why this is the risky one)

Local healing works because **everything needed is in one tree**: darnlink walks the tree, builds a
`uuid → path` index, and rewrites stale paths — deterministic, offline, no external state (Principles
III & IV). A cross-repo URL breaks that premise: reading the `uuid` that lives in a **different repo**
forces either the **network** (→ collides with **P-IV**, "no network calls"), a **shared committed
index/manifest** (→ collides with **P-III**, "no external database, no index file"), or **declining to
resolve** and pushing it out of band. There is no free version; this spec picks the least-bad one openly.

---

## Decision (chosen by txemi): online-fetch, opt-in, OFF by default

darnlink gains a **separate, opt-in `web-check --online`** mode that, for each cross-repo web link,
**fetches the ONE destination URL** (not a crawler) via the GitHub Contents API, reads its frontmatter
`uuid`, and:

- **plain web link** + destination has a `uuid` → **anchor** the link (`[text](url) <!-- uuid: X -->`);
  report under dry-run, apply under `--write`.
- **already-anchored web link** → **verify** the link's `uuid` still matches the destination's; on
  **mismatch or 404**, report and exit non-zero.

It **does not** search where a moved file went — there is no web-side index to walk (unlike the local
case). Finding the new location of a moved cross-repo target is left to the **layer above** (an LLM /
human), which can then re-anchor. darnlink's job here is narrow: *anchor when it can read the target,
verify when it already has a uuid, and fail loudly when the two disagree.*

**Why the offline-checkout idea was dropped.** An earlier draft resolved offline against sibling repo
checkouts the caller supplies. It kept P-IV but assumed the consumer always has the other repo checked
out beside the first; the real deployment does not want that coupling, and the online fetch is what maps
to how the docs are actually authored and split. The offline path is recorded here only as the rejected
alternative (see §Alternatives).

### The two layers (the constitution's split, applied)

- **Core stays offline & unchanged.** By default `darnlink` / `check` / `robustify` **IGNORE** web links
  entirely — a web link is never treated as broken (before this feature the core *wrongly* flagged an
  anchored web link `unresolvable`; that guard is fixed here — see FR-002/§Cost). Without `--online`
  there is **zero** new behaviour and **no** network.
- **`--online` is the opt-in escape hatch.** It is the only path that touches the network, exactly the
  `--online` mode the spike's first Constitution Check named as the price of cross-repo resolution.

---

## Constitution Check *(mandatory — the point of the spike)*

Reviewed against `.specify/memory/constitution.md` v1.0.0.

- **P-I Single Responsibility (links & UUIDs only, NON-NEGOTIABLE):** the two **core** operations
  (`robustify`/`repair`) are untouched. Web handling is a **separate subcommand** reusing the same
  `uuid`-in-frontmatter primitive; no entity model, no document semantics. The only new competence is
  "parse a GitHub blob URL + fetch one file", confined to `web-check`. **Held, with the amendment that
  P-I must bless a non-core subcommand** (see §Amendments). ✅ (conditioned)
- **P-II Safe by Default (dry-run first):** `web-check` is **report-only unless `--write`**; `--write`
  requires `--online` and only ever edits the **source** file (adds the `<!-- uuid: X -->` comment) —
  never the destination repo. Dry-run mutates nothing. **Held.** ✅
- **P-III Plain, Self-Contained, Tool-Agnostic (no external DB/index):** the link is plain Markdown that
  renders/clicks anywhere; **nothing is stored** in either repo — no manifest, no index file. Resolution
  is a live fetch, not a persisted artifact. A darnlink-less repo is fully usable. **Held.** ✅
- **P-IV Deterministic — No Heuristics, No Network:** `--online` **makes a network call → a deliberate,
  knowing violation of P-IV, contained to the opt-in mode.** The default path stays pure and offline.
  **Amendment required:** P-IV must gain an explicit carve-out naming `--online` as the sole sanctioned
  exception (see §Amendments). ⚠️ (violated on purpose, opt-in, off by default)

**Bottom line:** the feature cannot enter the **core** without breaking P-III or P-IV. It *can* live as
an **opt-in, off-by-default `web-check --online`** whose only principle cost is a **named P-IV carve-out
for the `--online` mode** — every other principle stands.

---

## Alternatives considered (and why rejected)

- **(b) committed `uuid → path` manifest per repo.** Offline & deterministic, but the manifest **is** the
  external index file P-III forbids; it rots the instant either repo is edited without re-running
  darnlink, reviving the predecessor's stale-index failure. **Rejected on P-III.**
- **(c) offline resolution against sibling checkouts** (`--repo owner/name=/path`). Keeps P-IV, but
  couples the consumer to always having the other repo checked out beside the first, and does not match
  how the docs are split/authored. **Rejected in favour of online-fetch** by txemi; kept here as runner-up.
- **Crawling the remote repo to find where a moved file went.** Out of scope: no web index exists to
  walk deterministically, and guessing violates P-IV's "no heuristics". Left to the LLM layer above.

---

## Requirements *(mandatory)* — scoped to the chosen online-fetch path

### Functional Requirements

- **FR-001** darnlink MUST recognise a **web link**: a Markdown link whose href is an `http(s)://` URL.
  A trailing `<!-- uuid: X -->` marks it **anchored**; without it the link is **plain**. Reuses the
  existing link + trailing-uuid grammar.
- **FR-002** The **core** operations (`repair`, `robustify`, `check`) MUST **ignore web links entirely**:
  a web link is never a repair/robustify/`unresolvable` finding. (This is the "ignore web by default"
  guard, `paths.is_web_href`, and it is a real behaviour change — before it, an anchored web link whose
  uuid is non-local was wrongly reported `unresolvable`, which would fail an existing gate.)
- **FR-003** `darnlink web-check PATH` with **no `--online`** MUST make **no network call** and add no
  new failure — it only lists the web links present (so the user knows `--online` exists). Exit 0.
- **FR-004** `darnlink web-check PATH --online` MUST fetch each web link's **single destination URL**
  (GitHub Contents API, stdlib `urllib`; **no crawling**), read the destination's frontmatter `uuid`,
  and classify the link (FR-005/FR-006). Each distinct URL is fetched at most once per run.
- **FR-005** **Anchor:** a **plain** web link whose destination has a `uuid` MUST be reported
  `web_anchor` (dry-run) and, under `--write`, rewritten to `[text](url) <!-- uuid: X -->`. `--write`
  MUST require `--online`. The write edits only the **source** file, never the destination repo.
- **FR-006** **Verify:** an **anchored** web link MUST be re-fetched and checked. Matching uuid →
  `web_ok`. Destination uuid absent or **different** → `web_mismatch` (a failure). A destination that
  **404s** → `web_not_found` (a failure). darnlink MUST NOT search for the moved file.
- **FR-007** **Auth:** the fetch MUST send `$GITHUB_TOKEN` when present (private repos) and work without
  it for public repos. A private destination with no usable token MUST be reported `web_unverifiable`
  (never a crash, never a silent pass — Constitution II).
- **FR-008** Parsing a GitHub URL into `(owner, repo, ref, path)` MUST be a pure textual function
  (deterministic, no network); an unrecognised URL shape is `web_unverifiable`, never a crash.
- **FR-009** Network/transport errors (timeout, DNS, connection reset) MUST map to `web_unverifiable`,
  never propagate as an exception.
- **FR-010** `--json` MUST emit web findings tagged by `kind` so a CI job can branch on them.
- **FR-011** Exit code: **0** clean/applied · **4** integrity failure (`web_mismatch` or `web_not_found`)
  · **3** anchors pending in dry-run (`web_anchor` present, no `--write`) · **1** usage error.
  `web_unverifiable` is reported but does **not** by itself fail the exit (it is not a broken link, only
  one this run could not confirm).

### Key Entities

- **Web link** — `[text](http(s)://…)` optionally followed by `<!-- uuid: X -->`. Renders/clicks as
  ordinary Markdown with no tooling; the `uuid` is the only anchor (no manifest, no stored index).
- **Web finding** — `web_ok` / `web_anchor` (uuid to add) / `web_mismatch` / `web_not_found` /
  `web_unverifiable`. A view over the single-URL fetch, not a new core model.
- **Fetcher** — `(GithubUrl, token) → (http_status, text|None)`. Network lives **only** here; injected
  in tests so no test touches the network.

## Acceptance (what the prototype demonstrates — all with a mocked fetcher)

1. **Anchor.** A plain web link + a destination that returns `uuid: X` → `web_anchor`; under `--write`
   the source becomes `[text](url) <!-- uuid: X -->`; dry-run changes nothing (exit 3).
2. **Verify OK.** An anchored link whose destination still returns the same uuid → `web_ok`, exit 0.
3. **Verify mismatch.** Destination returns a different uuid (or none) → `web_mismatch`, exit 4.
4. **Moved / 404.** Destination 404s → `web_not_found`, exit 4 (darnlink does not hunt for the new path).
5. **Private, no token.** Destination returns 403 and no `$GITHUB_TOKEN` → `web_unverifiable`, exit 0
   (honest, never a false pass); with a token the same fetch returns 200 and verifies.
6. **Core untouched.** `darnlink` / `--robustify` / `check` ignore the web link entirely (exit 0).
7. **Off by default.** Without `--online`, the fetcher is never called; report-only; exit 0.
8. **Report-only unless --write.** The verify path never mutates disk (checksums unchanged).

## Out of scope (for the spike)

- **Crawling / moved-file discovery** — left to the LLM layer above; darnlink only fetches the one URL.
- **URL rewriting for a moved target** (only *anchoring* a plain link and *verifying* an anchored one
  are in scope; healing a 404 to a new path is not).
- **Non-GitHub forges** (GitLab/Gitea URL shapes) — the parser is GitHub-only in the spike.
- **Any committed manifest** (alternative b) — rejected on P-III grounds.

## Amendments the Constitution WOULD need if this is ever merged to `main`

- **P-IV** — add: *"Network calls are forbidden in the core and in every default path. A single opt-in
  `--online` mode may fetch a named destination URL to read its `uuid`; it is the only sanctioned
  exception, is off by default, and never runs implicitly."* Also acknowledge that in `--online` the
  output is a function of *the tree **and** the live responses* — determinism is conditional there.
- **P-I** — add a sentence blessing a **separate, non-core subcommand** for cross-repo web links, and
  affirming the **two core operations remain exactly two** (web resolution is an adjunct, not a third).
- **The "Two Operations" section** — a note that web resolution is deliberately **not** a third core
  operation, to prevent the scope-creep that sank the predecessor.
- **P-III** stays as-is (no external index/manifest is introduced) — it is the principle this design was
  shaped to preserve, and the reason (b) was rejected.
