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

- **The snapshot is post-remediation.** Earlier the same day, 11 links that would otherwise sit in
  this bucket were fixed by hand — `uuid` added to 8 destination files, then anchored — precisely to
  keep the new axis's opening budget small. An earlier count that day is deliberately **not** quoted
  here: it was taken under a different scope and the two numbers do not reconcile, and a figure that
  invites a subtraction it does not support is worse than no figure.
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

The new finding fires **only** for: destination fetched 200 · its frontmatter has no `uuid` and is not
rejected by the reader · owner is in the owner set. Two exclusions on top of that (a third, free one —
an href that cannot be sent has no owner at all — is in §Prerequisite):

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
`^[0-9a-fA-F]{7,40}$` and nothing else — case-folded, like FR-001 and FR-005. A tag-pinned link
that genuinely cannot be fixed uses the FR-011
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

The budget is **`--own-max N`**: fail only above it, and say where the count stands relative to it —
in all four cases, not only when it drops (FR-013). Without it, switching the axis on fails several repos at once on day one, and an axis
that cannot be adopted incrementally gets turned off instead of obeyed — the lesson 015 already paid.

**The gate-recipe wiring is deliberately NOT in this spec.** Three review rounds spent their findings
on it — on which config key shape avoids a sentinel collision, on what a `bail()` does to the axes
after it, on the fact that the PowerShell recipe has drifted far enough that "both recipes" is not one
requirement but two. None of that is about *this* feature: it is about how a gate consumes any
darnlink exit code, it touches two shell surfaces this spec has no acceptance criteria for, and it is
exactly how `dangling_max` was done — the axis landed first, the recipe key followed in its own change.
Same here. What this spec owes the recipe is a CLI it can call and an exit contract it can trust;
those are FR-012, FR-013 and FR-017.

**And the budget must live in darnlink, not in the gate — that part does belong here**, because it
shapes the CLI. `dangling_max` could live in the recipe because the recipe re-counts those findings
itself. The web pass cannot: it takes `web-check`'s exit code verbatim, and exit 4 is **shared** with
`web_mismatch` / `web_not_found`, so from outside there is no way to tell a budgeted finding from a
genuinely dead link without re-running everything as `--json` and giving up the human report. Hence a
flag, not a key: `--own-max N` suppresses `web_own_no_uuid`'s contribution to the exit code while the
count is at or below `N`, and the findings are still reported — a budget silences the *verdict*, never
the *finding*. See FR-012/FR-013.

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
the exemption first and no anchor, today's `--write` inserts the anchor *before* the untouched
exemption, so the line **self-heals into the normative order** — no corruption. (Once FR-011 ships
that self-heal is no longer observable, because an exempt link is never anchored at all; the point
survives as the reason the *other* order is the dangerous one.) The corruption is a different case:
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

## Prerequisite — resolved upstream while this spec was in review

`web-check --online` used to **crash** — not fail, raise — on an href containing whitespace or a
control character, and again on a non-ASCII path. **Fixed in `main`**: the href is now rejected before
the parse, every URL field is percent-encoded, and a client-side URL error maps to its own
non-retryable sentinel rather than escaping the `except` clause. This spec no longer waits on it.

Two things survive the fix and belong here:

- **A third exclusion, free and already in place.** An href that cannot be sent yields no
  `GithubUrl` at all, so it has no owner and can therefore never be `web_own_no_uuid`. It is not
  listed beside FR-005 and FR-006 because it is not a rule this feature applies — it is a consequence
  of the parser refusing the input — but an implementer should know why that path never reaches the
  new finding.
- **013's wording is still wrong**, even though its code is now right: FR-008 covers an *unrecognised*
  URL shape (the regex accepted these) and FR-009 is worded for *transport* errors (this was
  client-side validation), so the crash fell through the gap between two requirements each written
  assuming the other covered it. See §Housekeeping.

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
  principle has never covered: the FR-011 exemption is a comment in the source Markdown, and the owner
  list will eventually be a key in a gate config (out of scope here — see §Adoption). Neither is a
  location database, neither rots into a stale index, and a darnlink-less repo still renders the
  Markdown unchanged. **Held.** ✅
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
- **Make the rule unconditional whenever the web axis is on, with no way to budget it.** Tempting, and
  it loses the one thing that makes the rung adoptable: a repo cannot cross from "several failures" to
  zero in one step, so it turns the axis off instead. Hence `--own-max`. (What this is *not* about:
  reaching the gate's `max` mode — the web pass already runs only there, so this rung inherits that
  reachability whatever is decided here. The budget is the point.)

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `web-check` MUST accept `--own OWNER`, repeatable. A destination whose parsed owner
  equals any given value (ASCII case-insensitive; the parser preserves the case it found, so the
  comparison must fold it) is **owned**. With no owner set, behaviour MUST be byte-identical to today
  **for every link that does not carry the FR-011 marker** — see FR-011 for why that marker is the one
  exception.
- **FR-002** `web-check` MUST accept `--own-from-origin`, which adds the owner of the scanned
  repository's `origin` remote to the owner set, accepting both the
  `https://github.com/<owner>/<repo>` and `git@github.com:<owner>/<repo>` forms. It MUST compose with
  explicit `--own` values (union). Resolution MUST use `git config --get remote.origin.url` executed
  in the scanned root, **not** a hand parse of `.git/config`: in a worktree `.git` is a *file*, not a
  directory, so a naive parse fails in the project's own development environment.
- **FR-003** If `--own-from-origin` cannot resolve an owner — no repository, no `origin`, a
  non-GitHub remote, `git` not on `PATH`, or `git` refusing the repository as dubiously owned
  (`safe.directory`, the failure mode of any tool run over someone else's checkout) — the run MUST
  exit **1** with a message naming the reason — **including
  when explicit `--own` values were also given**, so the owner set would not have been empty. It is a
  request that either succeeds or is a usage error; it never silently narrows the question answered.
- **FR-004** A link classified `web_unverifiable` **solely** because the fetched destination returned
  200 with **no frontmatter at all, or frontmatter without a `uuid`**, whose owner is owned, MUST
  instead be reported **`web_own_no_uuid`**, and MUST set the exit code to **4** (subject to FR-012).
  A destination whose frontmatter is present but **rejected by the canonical reader** — unparseable
  YAML, or a `uuid` that is not a string scalar — MUST NOT produce it — it stays
  `web_unverifiable` — because telling someone to *add* a `uuid` to a file whose frontmatter does not
  parse is the wrong instruction for a different defect. Note where the work is: the frontmatter reader
  **already** distinguishes absent from invalid; it is the caller that throws the distinction away by
  taking only the second element of its result. Keeping it is a one-character change, not a new
  parser.
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

  **The marker is honoured whether or not an owner set was given, and whether or not the destination is
  owned.** It states a property of the *link* — "this destination regenerates, never anchor it" —
  not of the run's configuration, and a marker that stopped working when someone dropped `--own` would
  let `--write` rewrite exactly the files it was placed to protect. This is the single, deliberate
  exception to FR-001's "byte-identical with no owner set". The marker MUST be recognised
  **immediately after the `)`, or immediately
  after a `web-uuid` anchor** — nowhere else. That is what makes the order enforceable rather than
  decorative: an anchor written *after* the marker is not seen, the link reads as plain, and `--write`
  appends a second one.
- **FR-012** `web-check` MUST accept **`--own-max N`**. While the number of `web_own_no_uuid` findings
  is **at or below** `N`, they MUST NOT contribute to the exit code; above `N`, FR-004's exit 4
  applies. The count is of **findings, not destinations**: two links in different files pointing at
  the same uuid-less file cost 2, and one edit at the destination clears both. `web_own_exempt` never
  counts. Other exit-4 causes are unaffected: one budgeted finding plus one real `web_not_found`
  still exits 4. The findings are always reported — the budget silences the *verdict*, never the
  *finding*. Omitting the flag MUST be distinguishable from `--own-max 0` (default `None`); the observable
  difference is FR-013's message, not the exit code, which is the same for both. `--own-max` without
  any owner set MUST be a usage error (exit 1).
- **FR-013** The report MUST always say where the count stands relative to the budget, in **four**
  branches — the shape the `dangling` precedent actually has, which an earlier draft of this
  requirement got wrong by naming only two:
  - **zero** → say to drop the flag entirely; the rule is a rule again.
  - **strictly below** a non-zero budget → say that lowering it to the count keeps the ratchet.
  - **exactly at** the budget → say so, and point at the next step (fix one, lower it by one).
    *"Lower the budget to 2" when the budget is already 2 instructs nobody*, and this is the state a
    repo sits in for most of an adoption, so it is the message printed most often.
  - **over** the budget → say so too. The run already fails on its own, but a budget that goes silent
    exactly when it is exceeded is the one moment its number is most worth reading.

  A budget nobody is told to lower is a budget that never goes down, which is why all four branches
  speak. Separately, when the count is **above zero** and within budget the run's **outcome word**
  MUST say so: today exit 0 prints `clean`, and printing `clean` with findings on screen is exactly
  the misreading this project's consumers have already paid for. At **zero** it must keep saying
  `clean` — an obsolete `--own-max 5` on an already-clean repo must not make a clean run look
  qualified. Unlike the four branches, this clause is conditioned on the exit code, because it is the
  word that reports it.
- **FR-014** The new finding MUST compose with the file-level opt-outs: a file carrying
  `darnlink-ignore-file` (003) or `darnlink-ignore-links` (006) MUST NOT produce it. The link is still
  fetched and still reported — it degrades to `web_unverifiable`, it does not vanish — because
  "never silent" is the same promise FR-011 makes, and a link that disappears from the report is one
  nobody can audit. Filtered links do not count toward FR-012's budget: they are not findings of that
  kind any more. This is a filter
  **by kind**, applied to `web_own_no_uuid` only — it MUST NOT suppress `web_mismatch`,
  `web_not_found` or any other web finding in that file, which would silently violate FR-007. That is
  a **third** semantics for those markers, narrower than the "removed from the darnlink graph
  entirely" the core gives them, and it is declared here rather than left to the implementer. Today
  `web-check` honours neither, so this is new work, not an existing guarantee (mirroring 015's
  FR-045). **And it goes no further than that:** FR-007 keeps `web_anchor` alive in such a file, so
  `--write` still anchors its plain web links. That sits uneasily beside 006's FR-033 ("left untouched
  by every operation"), and deliberately so — closing it is a change against 006's contract, not a
  corner of this one, and it must not be smuggled in here.
- **FR-015** `--ignore-block` is **out of FR-014 and unchanged**. It already suppresses the link
  *before any finding exists* (`find_web_links` skips the span), so it emits nothing at all today.
  Folding it into FR-014's by-kind rule would make links inside an ignored region start producing
  `web_not_found` — a behaviour change FR-007 forbids. Stated because the natural reading of "compose
  with the existing opt-outs" gets this backwards.
- **FR-016** The **text report** — not only `--json` — MUST carry both new kinds: counted in the
  summary line beside the existing five, and listed like any other actionable finding. FR-011's
  promise ("never silent, so whoever audits the repo can see the exemption") is not kept by a JSON
  mode nobody reads in a gate log.
- **FR-017** `--own`, `--own-from-origin` or `--own-max` **without `--online`** MUST be a usage error
  (exit 1), by the same argument as FR-003 and following the precedent `--write` already sets. The
  offline branch ignores them entirely, so accepting them silently would report a green run that never
  applied the rule it was asked for.

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

**Two axes, not one.** An earlier draft of this section was a single "first match wins" list, and it
was wrong in both directions: it made an exempt link whose destination 404s report `web_own_exempt`,
which FR-011 forbids four lines earlier, and it left the entire status-based classification out — the
layer that in fact decides most verdicts.

**Axis 1 — visibility, before any fetch:**

1. `--ignore-block` region or code fence → the link is **never seen**; nothing is emitted (FR-015).
2. A file carrying `darnlink-ignore-file` / `darnlink-ignore-links` → the link is fetched and
   classified as today, but `web_own_no_uuid` is filtered out of the result (FR-014).

**Axis 2 — classification, after the fetch. Status decides first:**

3. Anything other than 200 — 401/403, the `-2` unreadable-repo sentinel, the `-3` unsendable-URL sentinel, 404, a transport error —
   keeps **exactly** today's kind, for every link, exempt or not (FR-007). In particular an exempt
   link whose destination 404s is `web_not_found`, because a dead link is dead either way.
4. On **200 only**: FR-011's exemption → `web_own_exempt`, which also covers the `web_mismatch` and
   `web_anchor` cases it lists. Otherwise FR-004 → `web_own_no_uuid` (subject to FR-012's budget) —
   **but only when FR-005 and FR-006 both allow it**, and only when the destination's frontmatter is
   absent or lacks a uuid rather than being invalid YAML. In every other case the verdict is today's,
   unchanged: `web_ok`, `web_anchor`, `web_mismatch` or `web_unverifiable`.

**FR-005 and FR-006 are carve-outs, never verdicts.** They say when FR-004 must *not* fire; they do
not turn a link into `web_unverifiable`. An earlier draft of this section listed them as a producing
step, which silently changed behaviour FR-007 forbids changing: a plain link on a SHA-pinned ref whose
destination *does* carry a uuid is `web_anchor` today, exit 3, and `--write` anchors it — reading them
as terminal made it `web_unverifiable`, exit 0, nothing written. Different kind, different exit,
different file on disk.

Two consequences worth stating because they are the ones a reader gets wrong: an exempt link that
verifies fine (200, anchored, uuid matches) reports **`web_own_exempt`, not `web_ok`** — the marker
describes the *link*, not the outcome of one run; and an exempt link to a `.py` or on a SHA-pinned ref
also reports `web_own_exempt`, because the author's explicit "leave this alone" is the more specific
statement.

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
6. **Owned, SHA-pinned.** `blob/<40-hex>/a.md`, `blob/<7-hex>/a.md` and the same 40-hex ref in
   **UPPERCASE**, 200 without uuid → all three `web_unverifiable`, exit 0. The uppercase case is the
   guard: a rule that did not fold case would make such a link an unfixable failure. **And the negative that guards FR-006:** `blob/v1.2.3/a.md` — a ref
   that looks like a tag — **does** produce `web_own_no_uuid`, exit 4. **And the carve-out is not a
   verdict:** the same SHA-pinned link whose destination *does* carry a uuid is still `web_anchor`,
   exit 3, and `--write` still anchors it.
7. **Owned, 404.** With and without token → `web_not_found` / `web_unverifiable` exactly as today.
8. **`--own-from-origin` resolves.** A repo whose `origin` is `git@github.com:owned/src.git` behaves
   as `--own owned`; the `https://` form parses identically; and `--own other --own-from-origin`
   treats **both** `other/…` and `owned/…` as owned (the union of FR-002).
9. **`--own-from-origin` cannot resolve.** No `origin` → exit 1, message names the reason, no findings
   emitted — **and the same with `--own explicit --own-from-origin`**, where the owner set would not
   be empty (FR-003).
10. **No extra fetch (FR-009).** The mocked fetcher is called exactly as many times as without any
    owner set.
11. **Opt-out.** A link followed by `<!-- darnlink-own-exempt -->` reports `web_own_exempt` and does
    not affect the exit code; the same link without the marker is `web_own_no_uuid`, exit 4. An exempt
    link whose destination **does** have a uuid is **not** reported `web_anchor` and is **not**
    rewritten under `--write`; an exempt **anchored** link whose destination uuid has **changed** is
    **not** `web_mismatch` (FR-011's third exemption, the one that makes the hatch escape). With both
    markers in the normative order the anchor is still recognised and the file is byte-identical after
    `--write`. **And the corruption case**: with the anchor written *after* the exemption, `--write`
    must not append a second anchor — the file ends with exactly one.
12. **Exempt, and precedence.** An exempt link to a `.py` and one on a SHA-pinned ref both report
    `web_own_exempt` rather than `web_unverifiable`; an exempt link that verifies cleanly reports
    `web_own_exempt`, **not** `web_ok`; and an exempt link whose destination **404s** reports
    `web_not_found`, exit 4 — status decides before the exemption (§Precedence).
13. **Owner case.** `--own OWNED` against a `owned/repo/…` URL is owned, and vice versa (FR-001).
14. **Budget.** With two owned uuid-less destinations: `--own-max 2` → both reported, exit **0**, the
    outcome word is not `clean`, and the report says the count is **exactly at** the budget and to fix
    one and lower it to 1 — not "lower it to 2", which would be a no-op; `--own-max 3` → the
    lower-it-to-2 nudge; `--own-max 1` → exit **4**, and the report still says where the count stands; `--own-max 2` with an additional real `web_not_found` → exit **4** (FR-012). `--own-max`
    with no owner set → exit 1. Two links in **different files** pointing at the **same** uuid-less
    destination count as **2** (FR-012 counts findings, not destinations).
15. **Composition.** The same failing link degrades to `web_unverifiable` — reported, not silent, and
    not counted against the budget — when its file carries `darnlink-ignore-file` and
    when it carries `darnlink-ignore-links`, while a `web_not_found` in that same file is **still
    reported** (FR-014's by-kind filter). A link inside an `--ignore-block` region produces **nothing
    at all**, as today — including no `web_not_found` (FR-015).
16. **Both kinds surface.** `--json` carries every `web_own_no_uuid` **and** every
    `web_own_exempt` in `findings` under those literal kinds, with a count of each in the summary
    object (FR-010); the **text** report counts both in its summary line and lists them (FR-016).
17. **The message does not lie.** The `web_own_no_uuid` text contains the owner, the repo, the path,
    and the word `frontmatter`, and does **not** contain `--write` (FR-008).
18. **Other classifications untouched (FR-007).** With an owner set, an owned destination that returns
    401/403, one that returns the `-2` unreadable-repo sentinel, one that returns the transport-error
    sentinel, and a non-GitHub URL each keep exactly the kind and exit contribution they have today.

19. **Usage errors.** `--own o`, `--own-from-origin` and `--own-max 1`, each **without `--online`**,
    exit 1 with no fetch (FR-017).
20. **The budget at zero.** With no owned uuid-less destinations and `--own-max 5` still set: exit 0,
    the outcome word is `clean`, and the report says to drop the flag (FR-013's zero clauses).
21. **Invalid frontmatter is a different defect.** An owned destination returning 200 whose frontmatter
    is present but unparseable → `web_unverifiable`, exit 0, and the message does **not** say to add a
    `uuid` (FR-004).
22. **The marker does not need an owner set.** A link carrying `<!-- darnlink-own-exempt -->` whose
    destination has a uuid, run with **no `--own` at all**, is `web_own_exempt` and is **not**
    rewritten by `--write` — the one deliberate exception to FR-001 (FR-011).

## Out of scope

- **The second rung** (failing owned `web_unverifiable` for 404 / unreadable repo) — named above,
  specified separately if wanted.
- **Writing the `uuid` into the destination repository**, by any means, including a checked-out
  sibling. Principle II; also 013's rejected alternative (c).
- **Non-GitHub forges** — ownership is parsed from the GitHub URL shape, as in 013.
- **Push-permission-based ownership** — rejected above.
- **The gate-recipe wiring** (`own_web*` keys, and how a recipe should treat this feature's exit 1).
  Cut deliberately — see §Adoption. What this spec owes a gate is a CLI and an exit contract.
- **`raw.githubusercontent.com` URLs.** 013's parser does not recognise that host at all (only
  `github.com/<owner>/<repo>/{blob,raw}/…`), so such a link never yields an owner and stays
  `web_unverifiable`. The measurement above counts only what the parser recognised at the time.
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
  amended for P-IV.
