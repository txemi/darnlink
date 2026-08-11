# Feature Specification: fail on cross-repo web links to **your own** repos whose destination has no `uuid`

**Feature Branch**: `016-own-repo-web-strictness`

**Created**: 2026-08-11

**Status**: Draft

**Input**: Feature 013 gave darnlink a cross-repo web axis: `web-check --online` anchors a plain web
link to the destination file's `uuid`, and verifies an already-anchored one. It is deliberately
forgiving, because the destination lives in **someone else's repository** and cannot be fixed from
here: when the destination returns 200 but carries **no `uuid`**, the link is reported
`web_unverifiable` and the run still exits 0 (013 FR-011).

That forgiveness is right for a third-party destination and **wrong for a destination you own**. If
the target repo is yours, "the destination has no uuid" is not an external limitation — it is a
missing two-line edit in a repo you control, and today nothing ever tells you so. This feature adds
an opt-in flag that names the owners you control, and turns exactly that case into a failure whose
message says what to add and where.

---

## The gap, precisely

`_classify` collapses two very different situations into one non-failing bucket:

| Situation | Today | Should be |
|---|---|---|
| 200, destination **has** a uuid, link plain | `web_anchor` (exit 3) | unchanged |
| 200, destination has **no** uuid, destination **not yours** | `web_unverifiable` (exit 0) | unchanged — you cannot fix it |
| 200, destination has **no** uuid, destination **yours** | `web_unverifiable` (exit 0) | **a failure**: add the uuid at the destination |
| 404 (with token, readable repo) | `web_not_found` (exit 4) | unchanged |
| 404 (no token) / repo unreadable | `web_unverifiable` (exit 0) | unchanged in this feature (see §The second rung) |

The distinguishing datum — the destination's **owner** — is already parsed and sitting unused in
`GithubUrl.owner`. Deciding ownership costs **no extra fetch**: it is a textual comparison on a value
the run already has.

---

## Evidence this gap is real (measured, not hypothetical)

Measured 2026-08-11 across a nine-repository private fleet, all of which already carry web links:

- **345** GitHub `blob`/`raw` links in Markdown; **265 (77%)** point at repositories owned by the
  same account as the linking repo. Cross-repo linking here is overwhelmingly *self*-linking.
- Of the **46** own links still plain, resolving each destination against a local checkout:
  **27 point at a `.md` whose frontmatter has no `uuid`** — every one of them invisible to every
  darnlink axis today. Only 7 would already be caught as `web_anchor`.
- Restricted to the repos that actually run the web axis today (`web: true`), the numbers are
  **11 links** blocked on **8 destination files** across 3 repositories. All 8 were hand-written
  documents; none was machine-generated.

Two secondary measurements shape the design:

- **In repos where the web axis is already on and fail-closed, the "destination has a uuid" column is
  zero.** That is structural, not luck: such a link fails the gate as `web_anchor`, so it gets
  anchored immediately. Everything still plain in those repos is, by construction, in the silent
  bucket this feature targets. The axis has no overlap with what already exists.
- **The practice is growing fast.** In the largest consumer, own web links went 1 → 3 → 3 → 39 →
  **191** over twelve months (146 of them anchored). A 27-link backlog is not the point; the open
  door is.

One repository in the fleet mixes **26 own plain links with 30 third-party ones in the same tree** —
the clearest statement of the problem: to tolerate the 30 you must today also tolerate the 26.

---

## Decision: an explicit owner list, `auto` as a convenience

`web-check` gains **`--own OWNER`** (repeatable). A web link whose destination owner matches (ASCII
case-insensitively, as GitHub logins are) is **owned**; every other link keeps today's behaviour
exactly.

`--own auto` derives the owner from the scanned repository's `origin` remote. It is a convenience,
**not** the primary mechanism, because the explicit list is the only one that survives the real
cases: a fork (origin is yours, the content is not), a vendored checkout of a foreign repo, and an
organisation you push to whose name is not your login.

**`auto` that cannot resolve is a usage error (exit 1), never a silent "nothing is owned".** Degrading
to zero owned links would produce a green run that means nothing — the exact false pass this feature
exists to remove (Principle II: never silent).

### What fails, and the two things that deliberately do not

The new finding fires **only** for: destination fetched 200 · destination has no `uuid` · owner is in
the `--own` list. Two exclusions, both from measured cases in the fleet:

- **A destination that is not `.md`** never fails. It cannot carry frontmatter, so demanding a `uuid`
  is incoherent. This mirrors 015's FR-044 (anchoring stays `.md`-only). Measured: 2 such links.
- **A destination pinned to an immutable ref** (a full 40-hex commit SHA) never fails. You cannot add
  frontmatter to a past commit, so the finding would be unfixable by construction. Measured: 2 such
  links against 262 on moving refs (`main`/`master`/`HEAD`).

### The finding, and why exit 4 and not 3

New kind **`web_own_no_uuid`**, exit **4** (integrity), not 3.

Exit 3 means "a plain link darnlink can anchor for you — re-run with `--write`". This one darnlink
**cannot** fix: the edit belongs to the destination repository, and Principle II forbids writing
there. Reporting it as 3 would promise a `--write` that does nothing. The message must therefore
carry everything the human or LLM layer needs to act in the *other* repo: owner, repo, path, and the
literal instruction to add a `uuid` to that file's frontmatter.

### The second rung (separate, off by default)

A stricter variant — *"a destination you own must be **verifiable at all**"* — would also fail the
`web_unverifiable` cases when the owner is yours: a 404 without a token, and a 404 in a repo the
token cannot read. The reasoning is sound (for your own repo, "I could not check" is a provisioning
failure, not an external limit), but it is a **different rung** and must ship off by default: turning
it on together with the base rule reproduces the wall of false breaks that 013's tokenless-404 carve
out was written to prevent. Not specified further here; named so the base rule is not quietly widened
into it later.

### Adoption: a budget, not a cliff

The gate recipe gains `own_web` (off · on) and **`own_web_max` (int, default 0)**, the same ratchet
shape as `dangling_max`: fail only above the budget, and print the "lower it to N" nudge when the
count drops. Without it, switching the axis on fails several repos at once on day one, and an axis
that cannot be adopted incrementally gets turned off instead of obeyed — the lesson 015 already paid.

### Escape hatch (required, and it is not 005's)

A destination may be **machine-regenerated**, where a `uuid` is futile: the next regeneration wipes it
and the anchor points at nothing — strictly worse than a plain link. That is exactly the case 005
handles with `--no-create-frontmatter-for`, but **005's deny-list cannot be reused here**: it matches
basenames of targets *in your own tree*, and from the linking repo you cannot see whether a file in
another repo is generated. Without an opt-out, such a link would be permanently un-greenable, and a
permanently red axis gets disabled. The opt-out belongs in the **source** repo (where the knowledge
is), not in the destination.

---

## Prerequisite (external to this spec)

`web-check --online` currently **crashes** — it does not fail, it raises — when a Markdown href
contains whitespace: `_GITHUB_BLOB_RE` accepts spaces in its path group, and `http.client.InvalidURL`
derives from `HTTPException`, not `OSError`, so it escapes `_fetch_once`'s `except` clause. This
violates 013's FR-008 (an unrecognised URL shape is `web_unverifiable`, never a crash) and FR-009 (no
transport error propagates as an exception). Any repository that mirrors third-party content is
liable to contain such an href. Fixed separately; this axis is not adoptable before it.

---

## Constitution Check *(mandatory)*

Reviewed against `.specify/memory/constitution.md` v1.1.0.

- **P-I Single Responsibility:** the new competence is *comparing one string from a URL darnlink has
  already parsed*. No document semantics, no entity model. It stays inside the non-core `web-check`
  adjunct; the two core operations remain two. **Held.** ✅
- **P-II Safe by Default:** the finding is report-only and, unlike every other web finding, is
  **unfixable by `--write` on purpose** — darnlink never writes to the destination repository. The
  feature adds no write path at all. **Held, and reinforced.** ✅
- **P-III Plain, Self-Contained:** nothing is stored in either repository. The owner list is *tool
  configuration* (a flag, or a key in the gate recipe alongside `mode`/`web`/`dangling`), not a
  `uuid → path` index — it is not the manifest 013 rejected under this principle. **Held.** ✅
- **P-IV Deterministic:** with an explicit `--own`, output remains a function of *(tree + live
  responses)* — the same conditional determinism 013 already declared, with nothing added. With
  **`--own auto` it also becomes a function of the clone's git configuration**: the same tree yields
  different verdicts in a fork or a mirror. That is a new, small dependency on state outside the
  tree, and it is why explicit is primary and `auto` opt-in. **Amendment required** (see below).
  ⚠️ (only for `auto`)

**Bottom line:** the base rule costs the constitution **nothing**; only the `auto` convenience needs a
named sentence in P-IV.

---

## Alternatives considered (and why rejected)

- **Infer ownership from push permission** (`GET /repos/{o}/{r}` → `permissions.push`). Semantically
  the most correct definition of "controllable", and it is the question the user actually means. But
  it costs a second request per repo, and the answer varies with the token: the same tree passes on a
  laptop with a write PAT and fails in CI with a read-only one. Verdict-by-credential is worse than a
  slightly coarse owner match. **Rejected on reproducibility.**
- **Make it unconditional (every 200-without-uuid fails).** Simple, and wrong: it fails on
  destinations nobody here can edit, which is precisely the behaviour 013 chose against.
- **Infer "own" from the destination repo being cloned next to the source.** Revives the
  sibling-checkout coupling 013 already rejected as alternative (c), and makes the verdict depend on
  what happens to be on disk.
- **Fold it into `mode: max`.** The web axis is already coupled to `mode=max` in the recipe; adding a
  second coupling would make this rung unreachable for any repo that cannot pay the local ratchet.
  It is a separate axis with a separate budget, like `dangling`.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `web-check` MUST accept `--own OWNER`, repeatable. A destination whose parsed owner
  equals any given value (ASCII case-insensitive) is **owned**. With no `--own`, behaviour MUST be
  byte-identical to today.
- **FR-002** `--own auto` MUST derive the owner from the scanned repository's `origin` remote,
  accepting both the `https://github.com/<owner>/<repo>` and `git@github.com:<owner>/<repo>` forms.
  It MUST combine with explicit `--own` values (union).
- **FR-003** If `--own auto` cannot resolve an owner (no repository, no `origin`, non-GitHub remote),
  the run MUST exit **1** with a message naming the reason. It MUST NOT proceed with an empty owner
  set.
- **FR-004** A link classified `web_unverifiable` **solely** because the fetched destination returned
  200 with no frontmatter `uuid`, whose owner is owned, MUST instead be reported
  **`web_own_no_uuid`**, and MUST set the exit code to **4**.
- **FR-005** FR-004 MUST NOT fire when the destination path does not end in `.md`.
- **FR-006** FR-004 MUST NOT fire when the URL's ref is an immutable full commit SHA (40 hex chars).
- **FR-007** No other classification changes. In particular a 404 (with or without token), an
  unreadable repo, a non-GitHub URL and a transport error MUST keep today's kind and exit
  contribution, owned or not.
- **FR-008** The `web_own_no_uuid` message MUST name owner, repo, destination path, and state the
  action (add a `uuid` to that file's frontmatter in that repository). It MUST NOT suggest `--write`.
- **FR-009** Ownership MUST be decided without any additional network request.
- **FR-010** `--json` MUST emit the new kind under its own `kind`, and include a `web_own_no_uuid`
  count in the summary object, so a gate can branch on it and apply a budget.
- **FR-011** A per-link opt-out MUST exist for destinations that are machine-regenerated, expressed in
  the **source** repository. A link carrying it MUST be reported as tolerated (never silently
  dropped) and MUST NOT contribute to the exit code.

### Key Entities

- **Owner set** — the values from `--own` (plus `auto`'s resolution). Pure configuration; never
  persisted in either repository.
- **`web_own_no_uuid`** — a fourteenth finding kind: a destination *you control* that has not been
  given the `uuid` its inbound cross-repo link needs.

## Acceptance (all with a mocked fetcher — no test touches the network)

1. **Owned, no uuid.** Plain link to `owned/repo/blob/main/a.md`, destination returns 200 with no
   `uuid`, `--own owned` → `web_own_no_uuid`, exit 4; the message names `owned/repo` and `a.md`.
2. **Not owned, no uuid.** Same fetch, `--own someone-else` → `web_unverifiable`, exit 0 (unchanged).
3. **No flag.** Same fetch, no `--own` → `web_unverifiable`, exit 0 (unchanged).
4. **Owned, has uuid.** Destination returns 200 with `uuid: X` → `web_anchor`, exit 3, and `--write`
   anchors it (the existing path is untouched by ownership).
5. **Owned, non-`.md` destination.** `owned/repo/blob/main/tool.py`, 200, no uuid → `web_unverifiable`,
   exit 0.
6. **Owned, SHA-pinned.** `owned/repo/blob/<40-hex>/a.md`, 200, no uuid → `web_unverifiable`, exit 0.
7. **Owned, 404.** With and without token → `web_not_found` / `web_unverifiable` exactly as today.
8. **`auto` resolves.** A tree whose `origin` is `git@github.com:owned/src.git` behaves as
   `--own owned`; both remote URL forms parse.
9. **`auto` cannot resolve.** No `origin` → exit 1, message names the reason, no findings emitted.
10. **No extra fetch.** The mocked fetcher is called exactly as many times as without `--own`.
11. **Opt-out.** A link marked with the FR-011 opt-out reports as tolerated and does not affect the
    exit code.

## Out of scope

- **The second rung** (failing owned `web_unverifiable` for 404 / unreadable repo) — named above,
  specified separately if wanted.
- **Writing the `uuid` into the destination repository**, by any means, including a checked-out
  sibling. Principle II; also 013's rejected alternative (c).
- **Non-GitHub forges** — ownership is parsed from the GitHub URL shape, as in 013.
- **Push-permission-based ownership** — rejected above.

## Amendments the Constitution needs

- **P-IV** — add to the network carve-out paragraph: *"The opt-in `--own auto` resolution reads the
  scanned repository's `origin` remote, so in that mode the output is also a function of the clone's
  git configuration; the explicit `--own` form has no such dependency and is the primary mechanism."*

No other principle changes: the base rule is a pure textual predicate over data the run already holds.
