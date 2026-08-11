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

Measured 2026-08-11 across a nine-repository private fleet, all of which already carry web links.
Scope of the count, so it is reproducible: Markdown outside vendored `clones/` and `mirrors/`, with
fenced code blocks excluded.

- **255** GitHub `blob`/`raw` links; **228 (89%)** point at repositories owned by the same account as
  the linking repo. Cross-repo linking here is overwhelmingly *self*-linking.
- **193 of those 228 are already anchored.** The axis is in daily use, not a proposal.
- The **35** still plain break down like this — one bucket each, in this order:

| Bucket | Count | Meaning |
|---|---|---|
| destination `.md` **without** `uuid` | **17** | invisible to every darnlink axis today — *this feature* |
| destination has a `uuid` | 5 | already caught as `web_anchor` where the axis is on |
| destination is not `.md` | 6 | can never carry frontmatter (FR-005) |
| destination repo not checked out locally | 7 | could not be resolved offline for this count |
| ref pinned to a commit SHA | 0 | none in the current snapshot (see FR-006) |
| destination file missing | 0 | would be `web_not_found`, not this |

Two secondary measurements shape the design:

- **In repos where the web axis is already on and fail-closed, the "destination has a uuid" bucket is
  empty.** That is structural, not luck: such a link fails the gate as `web_anchor`, so it gets
  anchored immediately. Everything still plain in those repos is, by construction, in the silent
  bucket this feature targets. The axis has no overlap with what already exists. (The 5 above all sit
  in repos that have not switched the axis on.)
- **The practice is growing fast.** In the largest consumer, own web links went 1 → 3 → 3 → 39 →
  **191** over twelve months. A 17-link backlog is not the point; the open door is.

Two caveats stated rather than buried, because the whole case rests on these numbers:

- **The snapshot is post-remediation.** On the day of measurement, 11 of these links were fixed by
  hand — `uuid` added to 8 destination files, then anchored — precisely to keep the new axis's opening
  budget small. An earlier count that day put the uuid-less bucket at 27, but under a **wider scope**
  (it included vendored `clones/` and `mirrors/`), so the two figures are **not subtractable**; only
  the 17 above is measured under the scope stated here.
- **The 17 is a floor, not a total.** Seven more links point at repositories not checked out locally,
  so they could not be resolved offline; some of those destinations may also lack a `uuid`. The honest
  headline is *"17 confirmed, up to 24"*.
- **Every ref in the fleet is a branch**: `main` 201, `master` 20, `HEAD` 7, and nothing else across
  all 228. The immutable-ref exclusion below is therefore **reasoning, not measurement** — it has zero
  occurrences today and is specified so the first one does not become an unfixable failure.

---

## Decision: an explicit owner list, `--own-from-origin` as a convenience

`web-check` gains **`--own OWNER`** (repeatable). A web link whose destination owner matches (ASCII
case-insensitively, as GitHub logins are) is **owned**; every other link keeps today's behaviour
exactly.

**`--own-from-origin`** is a separate boolean flag that adds the owner of the scanned repository's
`origin` remote to that list. It is a convenience, **not** the primary mechanism, because the
explicit list is the only one that survives the real cases: a fork (origin is yours, the content is
not), a vendored checkout of a foreign repo, and an organisation you push to whose name is not your
login.

It is a **separate flag and not a magic `--own auto` value** on purpose: a sentinel inside a list of
owner names is unexpressible for anyone whose account or organisation is literally called `auto`, and
a flag that cannot name a legal input is a defect waiting for its first user.

**`--own-from-origin` that cannot resolve is a usage error (exit 1), never a silent "nothing is
owned".** Degrading to zero owned links would produce a green run that means nothing — the exact
false pass this feature exists to remove (Principle II: never silent).

**And that holds even when explicit `--own` values were also given** — the owner set would not be
empty, and it still exits 1. The rule is about the *request*, not about the resulting set: the caller
asked darnlink to discover an owner and it could not, so any verdict printed afterwards answers a
narrower question than the one asked. Reporting green on a subset the user did not fully specify is
the same false pass by a smaller door.

### What fails, and the two things that deliberately do not

The new finding fires **only** for: destination fetched 200 · destination has no `uuid` · owner is in
the owner set. Two exclusions:

- **A destination that is not `.md`** (compared case-insensitively, as `iter_markdown_files` already
  does) never fails. It cannot carry frontmatter, so demanding a `uuid` is incoherent. This mirrors
  015's FR-044 (anchoring stays `.md`-only). Measured: 6 such links.
- **A destination pinned to a commit SHA** never fails: you cannot add frontmatter to a commit that
  is already made, so the finding would be unfixable by construction.

**The exclusion is textual, and stops there — deliberately.** An earlier draft of this spec widened
it to *"any ref that is not a moving branch head"*, to also cover tags. That was a mistake and it is
recorded here so it is not reintroduced: **`v1.2.3` as a tag and `v1.2.3` as a branch are textually
identical**, so honouring it would require `GET /repos/{o}/{r}/git/refs` — a network call, against
FR-009 and against the "no extra fetch" acceptance — and its failure direction is the worst one: a
maintenance branch (`v2`, `release-1.2`) would be excluded for *looking like* a tag, producing a
false green, which is the exact failure this feature exists to remove. The rule is therefore
`^[0-9a-f]{7,40}$` and nothing else. A tag-pinned link that genuinely cannot be fixed uses the FR-011
marker, which is what it is for.

That rule has its own small false-green — a branch named `deadbeef` — accepted knowingly: it is
textual, offline, auditable, and its failure mode is one link, not a class of them.

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

The gate recipe gains `own_web` (a list of owner names), `own_web_from_origin` (a boolean) and
**`own_web_max`**: fail only above the budget, and print the "lower it to N" nudge when the count
drops. The boolean is separate for the same reason the CLI has a separate flag and not an `auto`
value — putting `origin` inside the list re-creates, one layer down, the sentinel collision this
design rejected above. Without it, switching the axis
on fails several repos at once on day one, and an axis that cannot be adopted incrementally gets
turned off instead of obeyed — the lesson 015 already paid.

**But the budget cannot be built the way `dangling_max` was, and that has to be said here or it will
be discovered during implementation.** `dangling_max` works because the recipe re-counts the findings
itself and computes the exit code. The web pass does the opposite: it runs `web-check` and takes its
exit code verbatim, marking it final. And exit 4 is **shared** with `web_mismatch` / `web_not_found`,
so from outside there is no way to tell a budgeted `web_own_no_uuid` from a genuinely dead link
without re-running everything as `--json` and giving up the human-readable report.

Therefore the budget lives in **darnlink**, not in the recipe: a `--own-max N` flag that suppresses
`web_own_no_uuid`'s contribution to the exit code while the count is at or below `N` (the findings are
still reported — a budget silences the *verdict*, never the *finding*). The recipe's keys are thin
pass-throughs. See FR-012/FR-013/FR-015.

### Escape hatch (required, and it is not 005's)

A destination may be **machine-regenerated**, where a `uuid` is futile: the next regeneration wipes it
and the anchor points at nothing — strictly worse than a plain link. Without an opt-out, such a link
is permanently un-greenable, and a permanently red axis gets disabled rather than obeyed.

**The marker is a trailing `<!-- darnlink-own-exempt -->` beside the link**, in the **source** repo —
where the knowledge lives:

```
See the [nightly export](https://github.com/owned/repo/blob/main/mirrors/export.md) <!-- darnlink-own-exempt -->
```

Because the same position already belongs to `<!-- web-uuid: X -->` — `_TRAILING_WEB_UUID_RE` is
applied immediately after the closing `)` — **the order is fixed and normative**: the anchor first,
the exemption second.

```
[text](url) <!-- web-uuid: X --> <!-- darnlink-own-exempt -->
```

**Measured, because the obvious rationale for this is wrong and was written down once already.** With
the exemption first and no anchor, `--write` inserts the anchor *before* the untouched exemption, so
the line **self-heals into the normative order** — no corruption. The corruption is a different case:
an anchor that already sits **after** the exemption,

```
[text](url) <!-- darnlink-own-exempt --> <!-- web-uuid: X -->
```

which the tail regex cannot see, so the link reads as plain and a **second** anchor is appended,
leaving two. That is the case the acceptance scenario must assert, and the reason the order is
normative rather than advisory.

Why not each of the three opt-outs that already exist, in the order someone will suggest them:

- **005's `--no-create-frontmatter-for`** matches *basenames of targets in your own tree*. From the
  linking repo you cannot see whether a file in another repo is generated, and the real names are
  unique per item (a mirrored message, a dated export), so there is no basename to deny.
- **006's file-level `darnlink-ignore-links`** is too blunt: it disables link handling for the
  **whole file**, including the core's intra-repo robustify. Exempting one cross-repo link must not
  cost the file its local link healing.
- **`--ignore-block`** works on regions, not links, and web-check already honours it by dropping the
  link **before any finding exists** — it is the right tool for a generated *section*, and it stays
  exactly as it is. It is not a per-link exemption, and FR-014 must not turn it into one.

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
  ⚠️ True of `--own OWNER`, **not** of `--own-from-origin`, which must locate a repository and read
  its remote — I/O of a kind the package does nowhere else today (there is no `subprocess` and no git
  access anywhere in `src/darnlink/`). Still no document semantics, so the principle holds, but that
  new competence is the **second** reason the flag is opt-in rather than the default.
- **P-II Safe by Default:** the finding is report-only and, unlike every other web finding, is
  **unfixable by `--write` on purpose** — darnlink never writes to the destination repository. The
  feature adds no write path at all. **Held, and reinforced.** ✅
- **P-III Plain, Self-Contained:** nothing is stored in either repository **as a `uuid → path`
  index** — that, and only that, is what this principle forbids, and it is why 013 rejected the
  manifest. Two things this feature does put in a repo, and both are ordinary configuration the
  principle has never covered: the owner list as the `own_web` key of the gate recipe's committed
  config (FR-015), and the FR-011 exemption as a comment in the source Markdown. Neither is a location
  database, neither rots into a stale index, and a darnlink-less repo still renders both. **Held.** ✅
- **P-IV Deterministic:** with an explicit `--own`, output remains a function of *(tree + live
  responses)* — the same conditional determinism 013 already declared, with nothing added. With
  **`--own-from-origin` it also becomes a function of the clone's git configuration**: the same tree
  yields different verdicts in a fork or a mirror. That is a new, small dependency on state outside
  the tree, and it is why explicit is primary and the flag opt-in. **Amendment required** (see below).
  ⚠️ (only for `--own-from-origin`)

**Bottom line:** the base rule costs the constitution **nothing**; only the `--own-from-origin`
convenience needs a named sentence in P-IV.

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
- **Exclude tags as well as SHAs from the failing rule.** Undecidable offline; rejected in
  §What fails above, with its failure direction.
- **Fold it into `web: true`, with no key of its own.** Tempting, and it loses the one thing that
  makes the rung adoptable: a **separate budget**. (Note what this alternative is *not* about:
  reaching `mode: max` — the web pass already runs only inside the recipe's `max` branch, so
  `own_web` is transitively mode=max-only whatever this bullet decides. The separate key buys the
  budget, not the reachability.) Same shape as `dangling` beside `mode`.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `web-check` MUST accept `--own OWNER`, repeatable. A destination whose parsed owner
  equals any given value (ASCII case-insensitive; the parser preserves the case it found, so the
  comparison must fold it) is **owned**. With no owner set, behaviour MUST be byte-identical to today.
- **FR-002** `web-check` MUST accept `--own-from-origin`, which adds the owner of the scanned
  repository's `origin` remote to the owner set, accepting both the
  `https://github.com/<owner>/<repo>` and `git@github.com:<owner>/<repo>` forms. It MUST compose with
  explicit `--own` values (union). Resolution MUST use `git config --get remote.origin.url` executed
  in the scanned root, **not** a hand parse of `.git/config`: in a worktree `.git` is a *file*, not a
  directory, so a naive parse fails in the project's own development environment.
- **FR-003** If `--own-from-origin` cannot resolve an owner (no repository, no `origin`, non-GitHub
  remote, `git` not on `PATH`), the run MUST exit **1** with a message naming the reason — **including
  when explicit `--own` values were also given**, so the owner set would not have been empty. It is a
  request that either succeeds or is a usage error; it never silently narrows the question answered.
- **FR-004** A link classified `web_unverifiable` **solely** because the fetched destination returned
  200 with no frontmatter `uuid`, whose owner is owned, MUST instead be reported
  **`web_own_no_uuid`**, and MUST set the exit code to **4** (subject to FR-012).
- **FR-005** FR-004 MUST NOT fire when the destination path does not end in `.md`, compared
  **case-insensitively** (`iter_markdown_files` already lowercases; `A.MD` is a Markdown file).
- **FR-006** FR-004 MUST NOT fire when the URL's ref matches `^[0-9a-fA-F]{7,40}$` — a commit SHA,
  long or short, in either case (GitHub accepts an uppercase SHA in a blob URL, and FR-001 and FR-005
  both fold case; a rule that did not would make such a link an unfixable failure). The test MUST be
  purely textual: no other ref shape is excluded, and in particular a tag MUST NOT be, because a tag
  is textually indistinguishable from a branch of the same name and telling them apart needs the
  network (see §What fails).
- **FR-007** No other classification changes. In particular a 404 (with or without token), an
  unreadable repo (the `-2` sentinel), a non-GitHub URL and a transport error MUST keep today's kind
  and exit contribution, owned or not.
- **FR-008** The `web_own_no_uuid` message MUST name owner, repo, destination path, and state the
  action (add a `uuid` to that file's frontmatter in that repository). It MUST NOT suggest `--write`.
- **FR-009** Ownership and every exclusion MUST be decided without any additional network request.
- **FR-010** `--json` MUST emit both new kinds (`web_own_no_uuid`, `web_own_exempt`) under their own
  `kind`, and include a count of each in the summary object, so a consumer can report on them.
- **FR-011** A link followed by **`<!-- darnlink-own-exempt -->`** MUST be exempt from **three**
  verdicts, and from exactly three:
  - **FR-004** (`web_own_no_uuid`) — the point of the marker.
  - **013's FR-005** (`web_anchor`) — an exempt link is never anchored, under `--write` or otherwise;
    anchoring it is the very damage the marker exists to prevent, since the destination's `uuid` will
    not survive its next regeneration.
  - **`web_mismatch`** — without this the escape hatch does not escape. A destination that
    regenerates is precisely one whose `uuid` drifts, and the normal migration path (adding the marker
    to a link anchored earlier) would otherwise leave a permanent exit-4 `web_mismatch` — the same
    dead end by another door.

  It MUST **not** exempt from `web_not_found`: a dead link is dead whether or not its destination is
  regenerated, and that is still worth failing on.

  When combined with an anchor the order is normative —
  `[text](url) <!-- web-uuid: X --> <!-- darnlink-own-exempt -->` — because both markers claim the
  position immediately after `)`. The link MUST still be reported, under the kind **`web_own_exempt`**,
  and MUST NOT contribute to the exit code: silently dropping it would hide the exemption from whoever
  audits the repo later.
- **FR-012** `web-check` MUST accept **`--own-max N`**. While the number of `web_own_no_uuid` findings
  is **at or below** `N`, they MUST NOT contribute to the exit code; above `N`, FR-004's exit 4
  applies. The count is of **findings, not destinations**: two links in different files pointing at
  the same uuid-less file cost 2, and one edit at the destination clears both. `web_own_exempt` never
  counts. Other exit-4 causes are unaffected: one budgeted finding plus one real `web_not_found`
  still exits 4. The findings are always reported — the budget silences the *verdict*, never the
  *finding*. Omitting the flag MUST be distinguishable from `--own-max 0` (default `None`), and
  `--own-max` without any owner set MUST be a usage error (exit 1).
- **FR-013** When the count is at or below a non-zero `--own-max`, the report MUST print the count and
  say that lowering the budget to that number keeps the ratchet; when the count reaches **zero** it
  MUST say to drop the flag entirely. Both nudges, as `dangling_max` gives. A budget nobody is told to
  lower is a budget that never goes down. The run's outcome word MUST also reflect the budget: today
  exit 0 prints `clean`, and printing `clean` with findings on screen is exactly the misreading this
  project's consumers have already paid for — under budget it MUST say so instead.
- **FR-014** The new finding MUST compose with the file-level opt-outs: a file carrying
  `darnlink-ignore-file` (003) or `darnlink-ignore-links` (006) MUST NOT produce it. This is a filter
  **by kind**, applied to `web_own_no_uuid` only — it MUST NOT suppress `web_mismatch`,
  `web_not_found` or any other web finding in that file, which would silently violate FR-007. That is
  a **third** semantics for those markers, narrower than the "removed from the darnlink graph
  entirely" the core gives them, and it is declared here rather than left to the implementer. Today
  `web-check` honours neither, so this is new work, not an existing guarantee (mirroring 015's
  FR-045).
- **FR-014b** `--ignore-block` is **out of FR-014 and unchanged**. It already suppresses the link
  *before any finding exists* (`find_web_links` skips the span), so it emits nothing at all today.
  Folding it into FR-014's by-kind rule would make links inside an ignored region start producing
  `web_not_found` — a behaviour change FR-007 forbids. Stated because the natural reading of "compose
  with the existing opt-outs" gets this backwards.
- **FR-015** **Both** gate recipes — the bash `darnlink-gate` and its PowerShell twin, which carries
  the same web pass and the same verbatim-exit-code contract — MUST expose `own_web` (a list of owner
  names), `own_web_from_origin` (bool) and `own_web_max` (int), passing them through as `--own` /
  `--own-from-origin` / `--own-max`. A single-surface implementation is how the two recipes have
  already drifted (`dangling_max` exists in one and not the other).
- **FR-016** Because FR-003 and FR-012 make **exit 1 reachable from a configuration typo**, the
  recipes MUST treat exit 1 from `web-check` as a *usage* error and MUST NOT report it as a repository
  verdict. It MUST NOT be routed to the recipe's `bail()` helper, which **exits the whole script**: a
  forgotten `own_web` beside an `own_web_max` would then produce a green gate that also silently skips
  the create-readme and dangling axes — the precise bug the recipe already documents and fixed once
  with `RC_IS_FINAL`. The required shape is the create-readme axis's: warn, preserve any already
  failing `rc`, and let every remaining axis run.

### Key Entities

- **Owner set** — the values from `--own` plus, if requested, the one from `--own-from-origin`. Pure
  configuration; never persisted as an index.
- **`web_own_no_uuid`** — the **sixth** web finding kind (beside `web_ok`, `web_anchor`,
  `web_mismatch`, `web_not_found`, `web_unverifiable`): a destination *you control* that has not been
  given the `uuid` its inbound cross-repo link needs.
- **`web_own_exempt`** — the **seventh**: a link whose FR-011 marker takes it out of the three
  verdicts listed there. Reported, never silent, never part of the exit code, and included in
  `--json` like any other kind (FR-010).

### Precedence, when several rules apply to the same link

Evaluated in this order, first match wins, so every combination has one answer:

1. **`--ignore-block` / code fence** — the link is never seen (FR-014b).
2. **FR-014's file markers** — `web_own_no_uuid` is filtered; other web kinds survive.
3. **FR-011's exemption** — `web_own_exempt`. It wins over FR-005/FR-006, so an exempt link to a
   `.py` or to a SHA-pinned path reports `web_own_exempt`, not `web_unverifiable`: the author said
   "leave this link alone", which is the more specific statement.
4. **FR-005 / FR-006** — `web_unverifiable`, unchanged.
5. **FR-004** — `web_own_no_uuid`, subject to FR-012's budget.

## Acceptance

The fetch layer is mocked in every scenario — no test touches the network. Scenarios 8 and 9 also need
a git fixture: a `tmp_path` with `git init` and a set (or absent) `remote.origin.url`, since FR-002
resolves through `git config`.

1. **Owned, no uuid.** Plain link to `owned/repo/blob/main/a.md`, destination returns 200 with no
   `uuid`, `--own owned` → `web_own_no_uuid`, exit 4; the message names `owned/repo` and `a.md`.
2. **Not owned, no uuid.** Same fetch, `--own someone-else` → `web_unverifiable`, exit 0 (unchanged).
3. **No flag.** Same fetch, no owner set → `web_unverifiable`, exit 0 (unchanged).
4. **Owned, has uuid.** Destination returns 200 with `uuid: X` → `web_anchor`, exit 3, and `--write`
   anchors it (the existing path is untouched by ownership).
5. **Owned, non-`.md` destination.** `owned/repo/blob/main/tool.py`, 200, no uuid → `web_unverifiable`,
   exit 0. And `owned/repo/blob/main/A.MD` **is** treated as Markdown (FR-005's case folding).
6. **Owned, SHA-pinned.** `blob/<40-hex>/a.md` and `blob/<7-hex>/a.md`, 200 without uuid → both
   `web_unverifiable`, exit 0. **And the negative that guards FR-006:** `blob/v1.2.3/a.md` — a ref
   that looks like a tag — **does** produce `web_own_no_uuid`, exit 4.
7. **Owned, 404.** With and without token → `web_not_found` / `web_unverifiable` exactly as today.
8. **`--own-from-origin` resolves.** A repo whose `origin` is `git@github.com:owned/src.git` behaves
   as `--own owned`; the `https://` form parses identically; and `--own other --own-from-origin`
   treats **both** `other/…` and `owned/…` as owned (the union of FR-002).
9. **`--own-from-origin` cannot resolve.** No `origin` → exit 1, message names the reason, no findings
   emitted — **and the same with `--own explicit --own-from-origin`**, where the owner set would not
   be empty (FR-003).
10. **No extra fetch.** The mocked fetcher is called exactly as many times as without any owner set.
11. **Opt-out.** A link followed by `<!-- darnlink-own-exempt -->` reports `web_own_exempt` and does
    not affect the exit code; the same link without the marker is `web_own_no_uuid`, exit 4. An exempt
    link whose destination **does** have a uuid is **not** reported `web_anchor` and is **not**
    rewritten under `--write`; an exempt **anchored** link whose destination uuid has **changed** is
    **not** `web_mismatch` (FR-011's third exemption, the one that makes the hatch escape). With both
    markers in the normative order the anchor is still recognised and the file is byte-identical after
    `--write`. **And the corruption case**: with the anchor written *after* the exemption, `--write`
    must not append a second anchor — the file ends with exactly one.
11b. **Exempt beats the other exclusions.** An exempt link to a `.py`, and an exempt link on a
    SHA-pinned ref, both report `web_own_exempt` rather than `web_unverifiable` (§Precedence).
12. **Owner case.** `--own OWNED` against a `owned/repo/…` URL is owned, and vice versa (FR-001).
13. **Budget.** With two owned uuid-less destinations: `--own-max 2` → both reported, exit **0**, the
    outcome word is not `clean`, and the report says to lower the budget to 2; `--own-max 1` → exit
    **4**; `--own-max 2` with an additional real `web_not_found` → exit **4** (FR-012). `--own-max`
    with no owner set → exit 1. Two links in **different files** pointing at the **same** uuid-less
    destination count as **2** (FR-012 counts findings, not destinations).
14. **Composition.** The same failing link is silent when its file carries `darnlink-ignore-file` and
    when it carries `darnlink-ignore-links`, while a `web_not_found` in that same file is **still
    reported** (FR-014's by-kind filter). A link inside an `--ignore-block` region produces **nothing
    at all**, as today — including no `web_not_found` (FR-014b).
15. **JSON shape.** `--json` carries every `web_own_no_uuid` in `findings` with that literal `kind`,
    plus a `web_own_no_uuid` count in the summary object (FR-010).
16. **The message does not lie.** The `web_own_no_uuid` text contains the owner, the repo, the path,
    and the word `frontmatter`, and does **not** contain `--write` (FR-008).
17. **Other classifications untouched (FR-007).** With an owner set, an owned destination that returns
    401/403, one that returns the `-2` unreadable-repo sentinel, one that returns the transport-error
    sentinel, and a non-GitHub URL each keep exactly the kind and exit contribution they have today.

## Out of scope

- **The second rung** (failing owned `web_unverifiable` for 404 / unreadable repo) — named above,
  specified separately if wanted.
- **Writing the `uuid` into the destination repository**, by any means, including a checked-out
  sibling. Principle II; also 013's rejected alternative (c).
- **Non-GitHub forges** — ownership is parsed from the GitHub URL shape, as in 013.
- **Push-permission-based ownership** — rejected above.
- **`raw.githubusercontent.com` URLs.** 013's parser does not recognise that host at all (only
  `github.com/<owner>/<repo>/{blob,raw}/…`), so such a link never yields an owner and stays
  `web_unverifiable`. The measurement above counts only what the parser recognises.
- **Repository renames and transfers.** Ownership is the owner **written in the URL**, not the current
  owner after a transfer — and GitHub's redirect makes the divergence invisible, because the fetch
  still succeeds. A repo you transferred away keeps reading as yours (an unfixable finding); one
  transferred to you keeps reading as someone else's (a missed one). Following the redirect to learn
  the current owner would cost a request per repo and reintroduce the credential-dependence that sank
  the push-permission alternative.

## Amendments the Constitution needs

- **P-IV** — add to the network carve-out paragraph: *"The opt-in `--own-from-origin` resolution reads
  the scanned repository's `origin` remote, so in that mode the output is also a function of the
  clone's git configuration; the explicit `--own` form has no such dependency and is the primary
  mechanism."*

No other principle changes: the base rule is a pure textual predicate over data the run already holds.

## Housekeeping this spec touches but does not do

- **013's header still says *"Status: Spike / EXPERIMENTAL … Do not merge to `main`"*** while the
  feature has been in `main` for releases and is gated by the recipe. This spec amends a document
  whose own status line is stale. Correcting it is a one-line change, deliberately left out of this
  PR so the amendment and the correction are reviewable apart.
- **FR-009 of 013** should be restated to cover client-side validation errors, not only transport
  errors — see §Prerequisite.
- **`_GITHUB_BLOB_RE` mis-parses a branch containing a slash.** `(?P<ref>[^/]+)` stops at the first
  separator, so `blob/release/1.2/docs/a.md` yields `ref='release'` and `path='1.2/docs/a.md'` — the
  wrong file, fetched and reported as `web_not_found`. Pre-existing in 013, but this spec makes `ref`
  load-bearing (FR-006) and rests part of its case on *"every ref in the fleet is a branch"*, so it is
  named here. Fixing it needs the ref/path split to be resolved against the repo's branch list, i.e.
  the network — the same wall as the tag question, and the reason it stays a known limit rather than a
  requirement.
- **P-II is untouched by the letter of this spec but not by its spirit**: `--own-from-origin` makes
  darnlink spawn an external process for the first time. Worth a sentence when the constitution is
  amended for P-IV, along with the `safe.directory` failure mode (`git` refusing a repo it considers
  dubiously owned), which FR-003 should list among its exit-1 reasons.
