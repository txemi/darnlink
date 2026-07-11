# Feature Specification: scope `--create-frontmatter` with a deny-list (`--no-create-frontmatter-for`)

**Feature Branch**: `005-no-create-frontmatter-for`

**Created**: 2026-06-09

**Status**: Draft

**Input**: Today `--create-frontmatter` is all-or-nothing: under it, robustify creates a minimal
frontmatter block on **every** plain-link target that lacks one. In a real repo, some targets are
**machine-regenerated** (a Jira/Teams export, a generated index) — a tool rewrites them on every
refresh. Creating a uuid in such a file is futile: the next regeneration wipes it, leaving the source
link anchored to a uuid that no longer exists (worse than a plain link). The author needs to
robustify the **hand-curated** targets (an `analysis.md`, a person sheet, a tool's `README.md`) while
**not** seeding uuids into regenerated companions in the same tree, in a single reproducible run
(e.g. a CI gate / pre-commit hook).

This feature adds an opt-out, **`--no-create-frontmatter-for GLOB`** (repeatable), that names target
**basenames** which must never have frontmatter *created* for them — even when `--create-frontmatter`
is on. It only narrows creation; everything else (reusing an existing uuid, repairing, reporting) is
unchanged.

## Why a deny-list on the basename (not an allow-list, not a path)

- **Deny-list, not allow-list**: the set of regenerated files is small and well-known
  (`content.md`, `transcript.md`, generated `_index.md`/`INDEX.md`, `PROJ-*.md`, …), while the set of
  hand-curated files is open-ended. Naming what to *exclude* is shorter and stays correct as new
  curated files appear.
- **Basename glob**: regenerated files are identified by their naming convention (a pipeline emits
  `content.md` everywhere), which is a basename pattern, not a path. Matching the basename with
  `fnmatch` keeps the gate declarative and location-independent (`--no-create-frontmatter-for
  'content.md'` covers every `content.md` under the tree). This is predictable and easy to audit.
- **Never given a uuid, consistently**: a denied target is never given a uuid — neither a new
  frontmatter block nor a uuid line inserted into existing frontmatter — **regardless of**
  `--create-frontmatter`. This is the least-surprising behavior for the intent ("this file is
  regenerated, leave it alone"): a regenerated file may well already carry frontmatter, and inserting
  a uuid there would still be wiped on the next refresh. Denied targets are reported `deny_listed`
  (distinct from `no_frontmatter`, whose "use --create-frontmatter" hint does not apply). A denied
  target that already has a valid uuid is unaffected (reuse is not creation).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Curated targets robustify, regenerated ones are left plain (Priority: P1)

In one tree, `A.md` links to a curated `analysis.md` (no frontmatter) and to a regenerated
`content.md` (no frontmatter). The author wants `analysis.md` anchored but not `content.md`.

**Acceptance Scenarios**:

1. **Given** `--create-frontmatter --no-create-frontmatter-for content.md`, **When**
   `darnlink --robustify --write` runs, **Then** `analysis.md` gets a new uuid and its link is
   robustified, while `content.md` is NOT modified, its link stays plain, and a `deny_listed`
   finding names it.
2. **Given** the same flags but `content.md` **already has** valid frontmatter with `uuid: U`,
   **When** robustify runs, **Then** its link is robustified reusing `U` (the deny-list gates
   *creation*, not reuse of an existing uuid).

---

### User Story 2 - Multiple patterns, glob matching (Priority: P2)

The author lists several regenerated basenames, some as globs.

**Acceptance Scenarios**:

1. **Given** `--no-create-frontmatter-for 'content.md' --no-create-frontmatter-for 'PROJ-*.md'`,
   **When** robustify runs with `--create-frontmatter`, **Then** neither `content.md` nor
   `PROJ-1533.md` gets frontmatter created, while other no-frontmatter targets do.

---

### Edge Cases

- **Flag without `--create-frontmatter`**: the deny-list still applies to its matched targets (they
  are never given a uuid) — for files with no frontmatter this is indistinguishable from the default
  (creation was already off), and for files *with* frontmatter it suppresses the uuid-line insertion
  the default would otherwise do. Non-matched targets behave exactly as before. No error.
- **Denied target already has a uuid**: untouched and its link is still robustified (reuse ≠ create).
- **Denied target has valid frontmatter but no uuid**: surgical insertion of a uuid into *existing*
  frontmatter is still giving a uuid to a regenerated file, so it is ALSO gated — left plain and
  reported `deny_listed`. (The deny-list means "never give this file a uuid"; both paths are gated.)
- **Reporting**: a denied target is reported with kind `deny_listed`, NOT `no_frontmatter` — the
  latter's "use --create-frontmatter to allow" hint would be misleading for a deny-listed file.
- **Glob matches a directory name component**: ignored — matching is on the file basename only.
- **Self-links / ignored-marker files / code blocks**: unchanged, orthogonal to this flag.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-028**: A new repeatable CLI option `--no-create-frontmatter-for GLOB` MUST collect basename
  globs. It is passed to `plan_robustify` as an ordered collection.
- **FR-029**: A plain-link target that has NO usable uuid and whose **basename** matches any deny-list
  glob (`fnmatch`) MUST NOT have frontmatter/uuid created or inserted — regardless of
  `--create-frontmatter` — and its link MUST be left plain. It MUST be reported with kind
  `deny_listed` (not `no_frontmatter`, whose "use --create-frontmatter" hint does not apply).
- **FR-030**: The deny-list MUST gate creation only. A denied target that already has a valid
  `uuid` MUST still be reusable (its links robustified), exactly as without the flag.
- **FR-031**: With no `--no-create-frontmatter-for` given, behavior MUST be byte-for-byte identical to
  before this feature (empty deny-list is a no-op).
- **FR-032**: Matching MUST be on the target's basename via `fnmatch` (case-sensitive on POSIX),
  deterministic and location-independent.

## Success Criteria *(mandatory)*

- **SC-015**: In a tree with a curated and a regenerated no-frontmatter target, a single
  `--robustify --write --create-frontmatter --no-create-frontmatter-for <regenerated>` run anchors
  the curated one and leaves the regenerated one plain + reported.
- **SC-016**: An empty deny-list reproduces prior output exactly (regression guard).
- **SC-017**: Deterministic & idempotent unchanged (a second run is a no-op).

## Assumptions

- The regenerated files in scope have no frontmatter today (the common case), so gating creation is
  sufficient to keep them out of the graph; the existing-uuid edge is handled by FR-030.
- Basename uniqueness of naming conventions (a pipeline emits the same basename everywhere) makes
  basename matching the natural identifier; path-scoped denial, if ever needed, is a later addition.

## Constitution Check

- **I. Single responsibility** — ✅ still links + uuid; this only narrows where uuid creation happens.
- **II. Safe by default** — ✅ strengthens safety: makes the opt-in creation step more granular, so a
  broad `--create-frontmatter` no longer seeds uuids into files that will be regenerated.
- **III. Plain, tool-agnostic** — ✅ no format change; output is the same robust-link format.
- **IV. Deterministic, no AI** — ✅ pure `fnmatch` on basenames; reproducible.
- **V. Test-first** — ✅ failing tests for the deny-list (curated-vs-regenerated, glob, no-op) first.

No violations. This refines an existing opt-in (`--create-frontmatter`) rather than adding a new
capability surface.
