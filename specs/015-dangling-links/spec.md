# Feature Specification: report links whose target does not exist (`dangling`)

**Feature Branch**: `015-dangling-links`

**Created**: 2026-08-09

**Status**: Draft

**Input**: A plain relative link pointing at a path that does not exist is invisible to darnlink
today. It is not `unresolvable` (that is a *robust* link whose uuid died), and it is not
`robustify` (there is no target to anchor). It falls out of the scan silently — not even as a
tolerated category. This feature surfaces it as a **report-only** finding: `dangling`.

## The gap, precisely

darnlink resolves a plain link's target to decide whether it can be robustified. That resolution
returns "no target" for **two very different situations**, and collapses them:

| Situation | Today | Should be |
|---|---|---|
| Target exists, is a `.md`, is in scope | `robustify` | unchanged |
| Target exists, is a `.md`, outside the scanned root | `out_of_scope` (FR-009) | unchanged |
| Target exists but is not a `.md` (`.py`, `.png`, a directory) | *(nothing)* | *(nothing — see FR-044)* |
| **Target does not exist at all** | *(nothing)* | **`dangling`** |

The first two already have their own categories, and `out_of_scope` is defined as *"robustify target
**exists** but was never scanned"* — so darnlink already distinguishes existence; it simply discards
the negative case instead of naming it.

## Evidence this gap is real (not hypothetical)

Measured 2026-08-09 across a fleet of **nine** consumer repositories that all run darnlink as their
link gate: **3,212 links point at paths that do not exist**, spread over 831 files. The largest
repository carries 2,526 of them; two are already at zero. None of these are reported by any darnlink
mode — `repair`, `check` or `max`.

Two of those repositories independently wrote **their own Markdown-link parser** to cover this (one
~150 lines, one ~100), each re-implementing link extraction, fenced-code skipping and exclude
handling that darnlink already does. One of them reads darnlink's own gate config to keep its excludes
in sync — evidence that the check belongs next to darnlink, not beside it. That is three parsers in a
fleet where the whole point of the gate recipe was to have one.

The trigger was mundane and is worth recording: a documentation reorganisation moved 78 Markdown files
in one commit. Every darnlink axis stayed green, because a link whose target no longer exists has no
uuid to fail on. The breakage was found by hand.

## Why this is in scope

Principle I limits darnlink to *"Markdown files, links, and a `uuid` frontmatter field"*, and refuses
"any feature that needs to understand the **meaning** of a document". This feature needs none:

- The **source** is always a Markdown file, as it is for every other finding.
- The **link** is a Markdown link darnlink already parses, already un-escapes, and already resolves.
- The question asked of the target is *"does this path exist?"* — a filesystem predicate. darnlink
  never opens the target, never parses it, never indexes it, and never writes to it.

It is also **not a third operation**. The scope boundary fixes the two *operations* (robustify,
repair) — not the number of things darnlink may report. Ten of the existing thirteen finding kinds are
diagnostics rather than operations; `invalid_frontmatter` is the precedent closest to this one:
*"reported, never touched"*, a diagnostic that falls out of parsing darnlink must do anyway. `dangling`
falls out of the resolution darnlink must do anyway.

Determinism (Principle IV) is preserved: a filesystem existence check is exact, offline, and
reproducible for a given tree.

## Why the target's type does not matter

The finding fires for **any** non-existent target, not only `.md` ones. Restricting it to `.md` would
report a missing `notes.md` and stay silent about an identical link to a missing `notes.txt`, which is
incoherent to the person reading the report — both are dead links in the same document.

Measured on the same fleet: **43%** of dangling targets are not `.md` (`.txt`, `.html`, `.py`, `.png`,
`.csv`, and directories). In the repository whose file move triggered this, **every** broken link
pointed at a `.csv`. A `.md`-only rule would therefore leave the motivating case entirely uncovered
and guarantee the duplicate parsers survive forever.

This does **not** widen what darnlink *manages*. Anchoring remains `.md`-only: a non-`.md` target can
never receive a `uuid` and can never be robustified (FR-044). The feature only lets darnlink say that
a link a Markdown document makes is dead.

## Why image embeds count (FR-050)

`MD_LINK_RE` has never excluded `![alt](path)`, so an image embed already travels the plain-link path;
it simply never survived `_anchor_target`, a `.png` being unanchorable. Naming the dangling case makes
that latent behaviour visible, so it has to be a decision rather than a side effect of a regex.

It is kept. A missing image is a broken document by the same standard as a missing link — arguably a
worse one, since it degrades to a broken-image glyph rather than to text a reader can still act on.
Excluding embeds would mean reporting `[x](gone.png)` and staying silent about `![x](gone.png)`, a
distinction with no bearing on whether the file is there.

Measured on the fleet: of the findings this feature adds over a hand-written checker that excluded
embeds, **six of fourteen were images pointing outside their repository** — screenshots that stopped
rendering when a home directory was reorganised, and that no gate had ever mentioned.

## Why an empty link text was the worse bug (FR-051)

FR-050 above reasons about embeds on the assumption that `MD_LINK_RE` sees them. For one very common
shape it did not: the pattern required `[^\]]+` — **at least one character** of link text — so
`![](photo.jpg)` matched nothing at all. Not reported and dismissed: **absent**, never a candidate.

That empty alt is not an edge case. It is what **pandoc emits for every image** when converting a
`.docx` or `.odt`, so it arrives in whole blocks of files imported at once, and the file that carries
it is exactly the kind nobody re-reads — a converted document, filed and trusted.

The failure mode is the one this whole feature exists to prevent, one level deeper. `dangling: 0` is
read as *"no broken links"*. It only ever meant *"none of the shapes the regex recognises"*, and the
gap between those two readings is invisible from the output. Measured on one repository running the
wall at maximum, in that repo's own gate scope: **127 links with empty text, of which 7 point at a
target that does not exist** — and the axis reported `dangling: 0`.

> ⚠️ **An earlier draft of this paragraph said "7 links of this shape, 7 broken, 0 with a target that
> exists, so the corpus offered no counter-example".** All three numbers were wrong, and the last was
> the dangerous one: it argued the change was safe *because* nothing else of this shape existed, when
> 83 links with a valid target and 36 web links did. The measurement behind it had counted a
> **narrower** shape than the sentence claimed — images carrying a pandoc attribute suffix, not
> empty-text links — and the gap was invisible because both counts were called "this shape". A
> widening is justified by what it newly matches, so counting the subset that motivated it and
> presenting that as the total inverts the argument.

Note what this is **not**. The bug was reported as the pandoc attribute suffix (`{width="1.1in"}`)
hiding the link. That suffix is harmless: the pattern stops at the `)` and never looks past it, and
`![alt](x.jpg){width="1.1in"}` was always seen. The two shapes co-occur because pandoc emits both at
once, which is what made the suffix the plausible-looking cause. Both are pinned in the tests so the
true cause cannot be re-diagnosed later from the same coincidence.

`href` keeps its `+`: a link with no destination has nothing to check. That was stated before it was
true — `[]()` never matched, but `[x]( )` did, and resolved to the linking file's own directory with
a blank name, producing a finding that read `line 5:  : target does not exist`. FR-052 makes the
behaviour match the claim. Two notes on scope, both learned by being wrong about them first:

- **It is a subtraction, not an addition.** With a non-empty text those shapes were reported *before*
  this release, so FR-052 removes findings from the pre-existing surface. Measured across thirteen
  local repositories, 14.446 Markdown files and 52.932 in-prose links: **0 occurrences**, so no
  consumer's count moves — but "0 findings lost" is a claim about the widening, and this rule is the
  one exception to it.
- **The guard belongs after `split_fragment` and `unquote`, not before.** Written against the raw
  href it missed `[](%20)` and `[]( #sec)` — the same destination, spelled differently — and the
  second was a false positive on valid CommonMark rather than a cosmetic finding.
- **And it has to strip, not just test for empty.** A first version rejected only an all-whitespace
  path, which left `[x]( B.md )` resolving to `dir/ B.md ` and reported dead — while this very
  section argued that surrounding whitespace is not part of the destination. A rule whose stated
  reason covers a case its code does not is worse than a narrower rule honestly scoped: the gap
  reads as a decision nobody took.

`ROBUST_LINK_RE` widens with `MD_LINK_RE` deliberately — leaving it narrow would make an anchored
`[](path) <!-- uuid: … -->` plain to one function and robust to another, and the tool's uuid
bookkeeping assumes those two agree. **That coupling is load-bearing for `repair`, not for
`dangling`**: an anchored empty-text link was invisible to *both* finders before, so its uuid never
reached the repair axis and a moved target silently stopped being healed — a false green one axis
over from the one this feature names. It needs its own tests, because reverting that half alone
leaves every `dangling` test green (measured: 0 failures before those tests existed, 3 after).

### What else the widening newly exposes

`MD_LINK_RE` has three call sites — `find_plain_links`, `find_detached_anchors` and
`find_web_links` — so the blast radius is not confined to `dangling`. Measured on the same
repository:

| Surface | Effect |
|---|---|
| `dangling` | +7 findings, all real broken image embeds; **0 findings lost** |
| web axis (`find_web_links`) | **+36** links newly visible. None is a `/blob/` URL, so none can demand an anchor and the gate does not flip — the shape of *these* URLs, not a property of the change. See the exit codes below |
| `robustify --write` | an existing target behind an empty-text link now receives a uuid anchor, and the `!` of an embed is preserved (both tested in `test_robustify.py`). **0 occurrences in the measured corpus**: every empty-text link with a live target points at an unanchorable image |
| `--create-readme` | `[](sub/)` and `![](media/)` can now **create** `sub/README.md`. 0 occurrences in the measured corpus, so this is live but unexercised |
| `find_detached_anchors` | absorption changes only where an empty-text link now legitimately claims a trailing comment. `DetachedAnchor` is not a reported `Kind`, so no finding disappears |

What a newly-visible `/blob/` URL would actually do, since a gate's exit code is the one thing this
tool exists to produce and an earlier draft of this paragraph had it **backwards**:

| Destination | Kind | Exit |
|---|---|---|
| reads, **carries** a uuid, link unanchored | `web_anchor` | **3** — anchors pending |
| reads, carries **no** uuid | `web_unverifiable` | 0 |
| 404 **with** a token that can see the repo | `web_not_found` | **4** — integrity failure, the harder stop |
| 404 without a token, or a repo the token cannot see | `web_unverifiable` | 0 |

⚠️ **One pre-existing write defect this widens the exposure to.** When a link carries a pandoc
attribute block, `--write` inserts the anchor *between* the link and its attributes —
`[](B.md) <!-- uuid: … -->{.cls}` — detaching them, since pandoc requires the block to follow the
`)` immediately. **Not introduced here**: a non-empty text does the same and always has. But the
corpus that motivated this feature is converted documents, where the block is ubiquitous, so the
widening routes many more links towards it. Filed as #65 rather than folded in — mixing a behaviour
change into a regression fix is how a fix stops being reviewable.

**Adopting a darnlink with this change is not a no-op for a consumer at `dangling: repo` with
`dangling_max` unset**: the repository above goes `0 → 7` and its push wall closes. The 7 links must
be fixed, or the ceiling raised, *before* the pin moves — not after.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-041**: A plain relative link in a scanned Markdown file whose resolved target path **does not
  exist** MUST be reported as a `dangling` finding, naming the file, the line, the link as written,
  and the resolved path. A dead link is acted on by opening it, so `file` + line is what makes the
  report usable without a search.

  > The line, link and resolved path travel in the finding's `detail`. This requirement used to add
  > *"no finding kind has ever carried a line field, and widening the shared `Finding` record is
  > outside this feature"* — **no longer true**: `Finding` grew an optional `line` (`report.py:37`)
  > for the gate recipe's added-lines ratchet, and `robustify.py:397` fills it. The `detail` text is
  > kept because callers parse it, not because the field is unavailable.
- **FR-042**: `dangling` MUST be **report-only**. No mode, including `--write`, may create, move or
  otherwise alter anything in response to it.
- **FR-043**: The target's extension MUST NOT affect whether the finding fires; only its existence.
- **FR-044**: A target that **exists** but is not an anchorable `.md` MUST NOT be reported as
  `dangling`, and MUST remain non-robustifiable exactly as today.
- **FR-045**: Detection MUST compose with the existing opt-outs: links inside fenced or inline code,
  inside an `--ignore-block` region, or in a file carrying `darnlink-ignore-links` /
  `darnlink-ignore-file` MUST NOT be reported.
- **FR-046**: Links with a URI scheme (`http:`, `mailto:`, …), protocol-relative links (`//…`) and
  pure fragments (`#…`) MUST NOT be reported. A fragment suffix on a relative path MUST be stripped
  before resolution.
- **FR-047**: Percent-encoded paths MUST be decoded before resolution, so a link to a file with a
  space is judged by the path it denotes.
- **FR-048**: A robust link (one carrying a `uuid` anchor) whose path is stale but whose uuid resolves
  MUST remain a `repair`, not a `dangling` — the uuid is the authority and the path is about to be
  fixed. `dangling` MUST NOT mask or duplicate `unresolvable`, `ambiguous` or `conflict`.
- **FR-049**: `dangling` MUST NOT change any existing exit code by itself. Which findings gate is the
  caller's policy, expressed in the gate recipe, not in the core.
- **FR-050**: An image embed (`![alt](path)`) whose target does not exist MUST be reported, on the
  same terms as any other link. See below — this is a decision, not an accident of the parser.
- **FR-051**: A link whose **text is empty** (`[](path)`, `![](path)`) MUST be detected on exactly
  the same terms as one with text. The link text is what a reader sees; it has no bearing on whether
  the destination is there, and requiring at least one character of it made such links invisible to
  every axis, not merely unreported. See below.
- **FR-052**: The whitespace **surrounding** a link destination MUST NOT be treated as part of it —
  CommonMark does not. So `[x]( B.md )` MUST be judged as `B.md`, and a destination that is *only*
  whitespace MUST NOT be reported at all: it names nothing, and resolving it yields the linking
  file's own directory under a blank name, a finding that names nothing a reader can act on. The
  rule is applied to the **decoded path with the fragment removed**, on the same terms as FR-046 and
  FR-047 — those spellings denote the same destination, and a rule applied to one of them is a rule
  with a way around it. Guarding the raw href alone left `[](%20)` and `[]( #sec)` still emitting
  the forbidden finding, the second on a legal in-page anchor (FR-046).

### Key Entities

- **`Kind.DANGLING`** — new finding kind. Detail carries the link as written and the resolved path.

## Acceptance

The cornerstone test: a Markdown file containing `[x](nope.md)`, `[y](nope.csv)` and `[z](nope/)`
where none of the three exist yields exactly three `dangling` findings; adding the three targets
yields none; and in both runs nothing on disk changes. A file carrying `darnlink-ignore-links` with
the same three links yields none.

## Out of scope

- **Gating.** Whether a `dangling` finding fails a build, and any staged/added-lines ratchet needed to
  adopt it on a repository with existing debt, belongs to the gate recipe — darnlink stays
  git-agnostic (spec 008, Option B).
- **Fixing.** darnlink does not guess where a missing file went. Repair by uuid is the mechanism for
  moved targets; a target that never existed is a human's problem.
- **Anchors in non-Markdown files.** Giving `.py` or other sources a `uuid` is a separate question,
  deliberately untouched here.
