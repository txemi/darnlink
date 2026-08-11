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
| 200, destination **has** a uuid, link plain | `web_anchor` (exit 3 in dry-run; 0 under `--write`) | unchanged |
| 200, destination has **no** uuid, destination **not yours** | `web_unverifiable` (exit 0) | unchanged — you cannot fix it |
| 200, destination has **no** uuid, destination **yours** | `web_unverifiable` (exit 0) | **a failure**: add the uuid at the destination |
| 404 (with token, readable repo) | `web_not_found` (exit 4) | unchanged |
| 404 (no token) / repo unreadable | `web_unverifiable` (exit 0) | unchanged in this feature (see §The second rung) |

The distinguishing datum — the destination's **owner** — is already parsed in `GithubUrl.owner` and
already used to build requests; it has simply never been used for **classification**. Deciding
ownership costs **no extra fetch**: it is a textual comparison on a value the run already has.

---

## Evidence this gap is real (measured, not hypothetical)

Measured 2026-08-11 across a nine-repository private fleet, all of which already carry web links:

- **345** GitHub `blob`/`raw` links in Markdown; **265 (77%)** point at repositories owned by the
  same account as the linking repo. Cross-repo linking here is overwhelmingly *self*-linking.
- Of the **46** own links still plain, resolving each destination against a local checkout:
  **27 point at a `.md` whose frontmatter has no `uuid`** — every one of them invisible to every
  darnlink axis today. Only 7 would already be caught as `web_anchor`. The rest of the 46: 2 target a
  non-`.md` file, 2 are pinned to a commit SHA, 1 target no longer exists, and for 9 the destination
  repository was not checked out locally, so they could not be resolved offline at all.
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

**And that holds even when explicit `--own` values were also given** — `--own me --own auto` in a
tarball with no `origin` still exits 1. The rule is about the *request*, not about whether the owner
set ends up empty: the caller asked darnlink to discover an owner and it could not, so any verdict it
prints afterwards is answering a narrower question than the one it was asked. Reporting green on a
subset the user did not fully specify is the same false pass by a smaller door.

### What fails, and the two things that deliberately do not

The new finding fires **only** for: destination fetched 200 · destination has no `uuid` · owner is in
the `--own` list. Two exclusions, both from measured cases in the fleet:

- **A destination that is not `.md`** (compared case-insensitively, as `iter_markdown_files` already
  does) never fails. It cannot carry frontmatter, so demanding a `uuid` is incoherent. This mirrors
  015's FR-044 (anchoring stays `.md`-only). Measured: 2 such links.
- **A destination pinned to an immutable ref** never fails. You cannot add frontmatter to a commit
  that is already made, so the finding would be unfixable by construction. "Immutable" is **not** just
  a 40-hex SHA: a **tag** and a **short SHA** are equally unfixable — re-tagging to plant a `uuid` is
  not a thing anyone will do. The rule is therefore *"the ref must be a moving branch head"*, and
  everything else is excluded. Measured: 2 SHA-pinned links against 262 on `main`/`master`/`HEAD`.

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

The gate recipe gains `own_web` (off · on) and **`own_web_max` (int, default 0)**: fail only above the
budget, and print the "lower it to N" nudge when the count drops. Without it, switching the axis on
fails several repos at once on day one, and an axis that cannot be adopted incrementally gets turned
off instead of obeyed — the lesson 015 already paid.

**But the budget cannot be built the way `dangling_max` was, and that has to be said here or it will
be discovered during implementation.** `dangling_max` works because the recipe re-counts the findings
itself and computes the exit code. The web pass does the opposite: it runs `web-check` and takes its
exit code verbatim, marking it final. And exit 4 is **shared** with `web_mismatch` / `web_not_found`,
so from outside there is no way to tell a budgeted `web_own_no_uuid` from a genuinely dead link
without re-running everything as `--json` and giving up the human-readable report.

Therefore the budget lives in **darnlink**, not in the recipe: a `--own-max N` flag that suppresses
`web_own_no_uuid`'s contribution to the exit code while the count is at or below `N` (the findings are
still reported — a budget silences the *verdict*, never the *finding*). The recipe's `own_web_max` is
then a thin pass-through, and it can keep taking the exit code verbatim exactly as it does today. See
FR-012/FR-013.

### Escape hatch (required, and it is not 005's)

A destination may be **machine-regenerated**, where a `uuid` is futile: the next regeneration wipes it
and the anchor points at nothing — strictly worse than a plain link. Without an opt-out, such a link
is permanently un-greenable, and a permanently red axis gets disabled rather than obeyed.

**The marker is a trailing `<!-- darnlink-own-exempt -->` beside the link**, in the **source** repo —
where the knowledge lives — with the same grammar and placement as the existing trailing markers:

```
See the [nightly export](https://github.com/owned/repo/blob/main/mirrors/export.md) <!-- darnlink-own-exempt -->
```

Why not each of the three opt-outs that already exist, in the order someone will suggest them:

- **005's `--no-create-frontmatter-for`** matches *basenames of targets in your own tree*. From the
  linking repo you cannot see whether a file in another repo is generated, and the real names are
  unique per item (a mirrored message, a dated export), so there is no basename to deny.
- **006's file-level `darnlink-ignore-links`** is too blunt: it disables link handling for the
  **whole file**, including the core's intra-repo robustify. Exempting one cross-repo link must not
  cost the file its local link healing.
- **`--ignore-block`** works on regions, not links, and web-check already honours it — it is the right
  tool for a generated *section*, and it stays available. It is not a per-link exemption.

**Composition is a requirement, not a bonus** — and it is not free today: web-check currently ignores
the 003 and 006 file-level markers entirely (it only skips `--ignore-block` regions and code fences).
015 made the equivalent explicit as its FR-045; this spec does the same in FR-014.

---

## Prerequisite (external to this spec)

`web-check --online` currently **crashes** — it does not fail, it raises — when a Markdown href
contains whitespace: `_GITHUB_BLOB_RE` accepts spaces in its path group, and `http.client.InvalidURL`
derives from `HTTPException`, not `OSError`, so it escapes `_fetch_once`'s `except` clause. Any
repository that mirrors third-party content is liable to contain such an href.

**And 013 does not actually forbid it — which is worse than a violation.** FR-008 covers an
*unrecognised* URL shape, and this one **is** recognised: the regex matches it happily and the run
dies later, at the fetch. FR-009 covers *"network/transport errors (timeout, DNS, connection reset)"*,
and a client-side URL validation error is none of those. So the crash falls through the gap between
two requirements that were each written assuming the other covered it. The fix therefore also wants
FR-009 restated as *"no error raised by the fetch layer — transport **or** client-side validation —
propagates as an exception"*. Fixed separately; this axis is not adoptable before it.

---

## Constitution Check *(mandatory)*

Reviewed against `.specify/memory/constitution.md` v1.1.0.

- **P-I Single Responsibility:** the new competence is *comparing one string from a URL darnlink has
  already parsed*. No document semantics, no entity model. It stays inside the non-core `web-check`
  adjunct; the two core operations remain two. **Held.** ✅
  ⚠️ True of `--own OWNER`, **not** of `--own auto`, which must find a repository root and read its
  git configuration — I/O of a kind the package does nowhere else today (there is no `subprocess` and
  no git access anywhere in `src/darnlink/`). Still no document semantics, so the principle holds,
  but that new competence is the **second** reason `auto` is opt-in rather than the default.
- **P-II Safe by Default:** the finding is report-only and, unlike every other web finding, is
  **unfixable by `--write` on purpose** — darnlink never writes to the destination repository. The
  feature adds no write path at all. **Held, and reinforced.** ✅
- **P-III Plain, Self-Contained:** nothing is stored in either repository **as a `uuid → path`
  index** — that, and only that, is what this principle forbids, and it is why 013 rejected the
  manifest. Two things this feature does put in a repo, and both are ordinary configuration the
  principle has never covered: the owner list may live as a key in the gate recipe's committed
  `darnlink-gate.json`, and the FR-011 exemption is a comment in the source Markdown. Neither is a
  location database, neither rots into a stale index, and a darnlink-less repo still renders both.
  **Held.** ✅
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
- **Fold it into `web: true`, with no key of its own.** Tempting, and it loses the one thing that
  makes the rung adoptable: a **separate budget**. (Note what this alternative is *not* about:
  reaching `mode: max` — the web pass already runs only inside the recipe's `max` branch, so
  `own_web` is transitively mode=max-only whatever this bullet decides. The separate key buys the
  budget, not the reachability.) Same shape as `dangling` beside `mode`.

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
  the run MUST exit **1** with a message naming the reason — **including when explicit `--own` values
  were also given**, so the owner set would not have been empty. `auto` is a request that either
  succeeds or is a usage error; it never silently narrows the question being answered.
- **FR-004** A link classified `web_unverifiable` **solely** because the fetched destination returned
  200 with no frontmatter `uuid`, whose owner is owned, MUST instead be reported
  **`web_own_no_uuid`**, and MUST set the exit code to **4**.
- **FR-005** FR-004 MUST NOT fire when the destination path does not end in `.md`, compared
  **case-insensitively** (`iter_markdown_files` already lowercases; `A.MD` is a Markdown file).
- **FR-006** FR-004 MUST NOT fire when the URL's ref is **not a moving branch head** — a full or
  short commit SHA, or a tag. Only a ref that can still receive a commit is fixable.
- **FR-007** No other classification changes. In particular a 404 (with or without token), an
  unreadable repo, a non-GitHub URL and a transport error MUST keep today's kind and exit
  contribution, owned or not.
- **FR-008** The `web_own_no_uuid` message MUST name owner, repo, destination path, and state the
  action (add a `uuid` to that file's frontmatter in that repository). It MUST NOT suggest `--write`.
- **FR-009** Ownership MUST be decided without any additional network request.
- **FR-010** `--json` MUST emit the new kind under its own `kind`, and include a `web_own_no_uuid`
  count in the summary object, so a gate can branch on it and apply a budget.
- **FR-011** A link followed by **`<!-- darnlink-own-exempt -->`** (same grammar and placement as the
  existing trailing markers, and combinable with a `web-uuid` anchor) MUST be exempt from FR-004. It
  MUST still be reported, as its own tolerated kind, and MUST NOT contribute to the exit code —
  silently dropping it would hide the exemption from whoever audits the repo later.
- **FR-012** `web-check` MUST accept **`--own-max N`** (default 0). While the number of
  `web_own_no_uuid` findings is **at or below** `N`, they MUST NOT contribute to the exit code; above
  `N`, FR-004's exit 4 applies. The findings are always reported: the budget silences the *verdict*,
  never the *finding*. `--own-max` without any `--own` MUST be a usage error (exit 1).
- **FR-013** When the count is at or below a non-zero `--own-max`, the report MUST print the count and
  say that lowering the budget to that number keeps the ratchet — the same nudge `dangling_max` gives.
  A budget nobody is told to lower is a budget that never goes down.
- **FR-014** The new finding MUST compose with the existing opt-outs: a file carrying
  `darnlink-ignore-file` (003) or `darnlink-ignore-links` (006), and any region inside an
  `--ignore-block` marker, MUST NOT produce it. Today `web-check` honours only `--ignore-block` and
  code fences, so 003 and 006 are new work here, not an existing guarantee (this mirrors 015's
  FR-045).

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
6. **Owned, immutable ref.** Three links, `blob/<40-hex>/a.md`, `blob/<7-hex>/a.md` and
   `blob/v1.2.3/a.md`, all 200 without uuid → all three `web_unverifiable`, exit 0.
7. **Owned, 404.** With and without token → `web_not_found` / `web_unverifiable` exactly as today.
8. **`auto` resolves.** A tree whose `origin` is `git@github.com:owned/src.git` behaves as
   `--own owned`; both remote URL forms parse.
9. **`auto` cannot resolve.** No `origin` → exit 1, message names the reason, no findings emitted —
   **and the same with `--own explicit --own auto`**, where the owner set would not be empty (FR-003).
10. **No extra fetch.** The mocked fetcher is called exactly as many times as without `--own`.
11. **Opt-out.** A link followed by `<!-- darnlink-own-exempt -->` reports under its tolerated kind and
    does not affect the exit code; the same link without the marker is `web_own_no_uuid`, exit 4.
12. **Owner case.** `--own OWNED` against a `owned/repo/…` URL is owned, and vice versa (FR-001); the
    parser preserves the case it found, so the comparison — not the parse — must fold it.
13. **Budget.** With two owned uuid-less destinations: `--own-max 2` → both reported, exit **0**, and
    the report says to lower the budget to 2; `--own-max 1` → exit **4**. `--own-max` with no `--own`
    → exit 1.
14. **Composition.** The same failing link is silent when its file carries `darnlink-ignore-file`,
    when it carries `darnlink-ignore-links`, and when it sits inside an `--ignore-block` region
    (FR-014).
15. **JSON shape.** `--json` carries every `web_own_no_uuid` in `findings` with that literal `kind`,
    plus a `web_own_no_uuid` count in the summary object (FR-010).
16. **The message does not lie.** The `web_own_no_uuid` text contains the owner, the repo, the path,
    and the word `frontmatter`, and does **not** contain `--write` (FR-008).
17. **Other classifications untouched (FR-007).** With `--own owned` set, an owned destination that
    returns 401/403, one that returns the transport-error sentinel, and a non-GitHub URL each keep
    exactly the kind and exit contribution they have today.

## Out of scope

- **The second rung** (failing owned `web_unverifiable` for 404 / unreadable repo) — named above,
  specified separately if wanted.
- **Writing the `uuid` into the destination repository**, by any means, including a checked-out
  sibling. Principle II; also 013's rejected alternative (c).
- **Non-GitHub forges** — ownership is parsed from the GitHub URL shape, as in 013.
- **Push-permission-based ownership** — rejected above.
- **`raw.githubusercontent.com` URLs.** 013's parser does not recognise that host at all (only
  `github.com/<owner>/<repo>/{blob,raw}/…`), so such a link never yields an owner and stays
  `web_unverifiable`. The 345-link measurement above counts only what the parser recognises.
- **Repository renames and transfers.** Ownership is the owner **written in the URL**, not the current
  owner after a transfer — and GitHub's redirect makes the divergence invisible, because the fetch
  still succeeds. A repo you transferred away keeps reading as yours (an unfixable finding); one
  transferred to you keeps reading as someone else's (a missed one). Following the redirect to learn
  the current owner would cost a request per repo and reintroduce the credential-dependence that sank
  the push-permission alternative.

## Amendments the Constitution needs

- **P-IV** — add to the network carve-out paragraph: *"The opt-in `--own auto` resolution reads the
  scanned repository's `origin` remote, so in that mode the output is also a function of the clone's
  git configuration; the explicit `--own` form has no such dependency and is the primary mechanism."*

No other principle changes: the base rule is a pure textual predicate over data the run already holds.

## Housekeeping this spec touches but does not do

- **013's header still says *"Status: Spike / EXPERIMENTAL … Do not merge to `main`"*** while the
  feature has been in `main` for releases and is gated by the recipe. This spec amends a document
  whose own status line is stale. Correcting it is a one-line change, deliberately left out of this
  PR so the amendment and the correction are reviewable apart.
- **FR-009 of 013** should be restated to cover client-side validation errors, not only transport
  errors — see §Prerequisite.
