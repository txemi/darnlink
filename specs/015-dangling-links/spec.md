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

## Requirements *(mandatory)*

### Functional Requirements

- **FR-041**: A plain relative link in a scanned Markdown file whose resolved target path **does not
  exist** MUST be reported as a `dangling` finding, naming the file, the line, the link as written,
  and the resolved path. The line, link and resolved path travel in the finding's `detail`: no
  finding kind has ever carried a line field, and widening the shared `Finding` record is outside
  this feature. A dead link is acted on by opening it, so `file` + line is what makes the report
  usable without a search.
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
