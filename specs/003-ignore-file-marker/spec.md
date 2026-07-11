# Feature Specification: per-file opt-out via an in-file marker

**Feature Branch**: `003-ignore-file-marker`

**Created**: 2026-06-08

**Status**: Draft

**Input**: A Markdown file must be able to declare, **from within itself**, that darnlink should
leave it alone entirely. The motivating case: generated files (e.g. a project's auto-built
`INDEX.md` / `PRIORITIES.md`) live inside directories darnlink should otherwise process; if
darnlink rewrites their links, the generator overwrites that work on its next run, producing a
churn loop. The current `--exclude` only skips whole directories by name, so it cannot single out
an individual file. This feature adds a self-contained, in-file opt-out — consistent with the
constitution's "everything needed is in the files themselves" (Principle III). It refines *which
files participate*; it does not add a new capability, so it does not amend Principle I.

## Why an in-file marker (vs CLI glob / ignore file)

A CLI `--exclude-glob` or a `.darnlinkignore` would work, but both keep the exclusion **outside**
the file: every caller (you, CI, a pre-commit hook, a newcomer running `darnlink .` raw) must know
the list, and a central list drifts when files are renamed. An in-file marker travels with the
file, survives moves, is self-documenting, and lets a generator emit the marker once so the file is
protected forever with zero CLI configuration. It is also the natural generalization of darnlink's
existing region-ignore mechanism (`<!-- NAME-start --> … <!-- NAME-end -->`): "ignore the whole
file" is simply "the file is one ignored block".

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A generated file opts itself out (Priority: P1)

A generator writes `<!-- darnlink-ignore-file -->` at the top of the file it produces. From then
on darnlink never rewrites that file's links and never indexes it as a link target — regardless of
the directory it sits in — so the generator and darnlink stop fighting.

**Why this priority**: It is the reason the feature exists; without it, darnlink cannot be adopted
on a tree that mixes generated and hand-authored Markdown in the same directories.

**Independent Test**: A file with the marker and a plain link; run `darnlink --robustify --write`;
assert the file is unchanged. Add a robust link to the same file from elsewhere by the file's UUID;
run `darnlink --write`; assert it is reported unresolvable (the ignored file is not indexed) and
nothing is written.

**Acceptance Scenarios**:

1. **Given** `G.md` contains `<!-- darnlink-ignore-file -->` and a plain link `[x](y.md)`,
   **When** `darnlink --robustify --write` runs, **Then** `G.md` is byte-for-byte unchanged.
2. **Given** `G.md` has the marker and a `uuid` in its frontmatter, and `A.md` has a robust link
   to that UUID, **When** `darnlink --write` runs, **Then** `G.md`'s UUID is **not** indexed, the
   link in `A.md` is reported *unresolvable*, and nothing is written (the ignored file is not a
   valid target).
3. **Given** `G.md` has the marker and is itself the target of a plain link from `A.md`, **When**
   `darnlink --robustify --write` runs, **Then** `G.md` gains **no** UUID and the link in `A.md` is
   left plain (an ignored file never becomes part of the graph).

---

### User Story 2 - Documenting the marker does not self-ignore (Priority: P2)

darnlink's own docs (and any file) must be able to *show* the marker as an example inside a code
block without accidentally opting themselves out.

**Acceptance Scenarios**:

1. **Given** a file whose only occurrence of `<!-- darnlink-ignore-file -->` is inside a fenced or
   inline code span, **When** darnlink runs, **Then** the file is processed normally (the marker
   inside code does not count). Composes with feature `002-ignore-code-blocks`.

---

### Edge Cases

- **Marker location**: anywhere in the file (not only the first line), as long as it is outside a
  code span.
- **Whitespace tolerance**: `<!--darnlink-ignore-file-->` and `<!--  darnlink-ignore-file  -->`
  both count. Canonical emission is `<!-- darnlink-ignore-file -->`.
- **Marker inside code**: does not count (feature 002).
- **Ignored file with links/UUID**: still fully skipped — not a source, not a target.
- **Robust link pointing at an ignored (thus unindexed) file**: reported *unresolvable*; never
  rewritten (exact-UUID determinism, no guessing).
- **Reporting**: the run reports how many files were skipped due to the marker (no silent caps,
  Constitution II).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-019**: A Markdown file containing the marker `<!-- darnlink-ignore-file -->` (outside any
  code span) MUST be skipped entirely by every operation: it is neither scanned as a source (its
  links are never rewritten/robustified) nor indexed as a target (its `uuid` is not resolvable).
  This is default behavior, not opt-in.
- **FR-020**: Marker detection MUST ignore occurrences inside fenced or inline code (composing with
  feature 002), so documentation showing the marker is unaffected.
- **FR-021**: Detection MUST be a pure textual check (deterministic, no network), tolerant of
  internal whitespace, matching the canonical keyword `darnlink-ignore-file`.
- **FR-022**: The run MUST report the count of files skipped via the marker (human and `--json`).

### Key Entities

- **Ignore-file marker**: an HTML comment `<!-- darnlink-ignore-file -->` that removes the file
  from the darnlink graph. Invisible when rendered; readable by any tool or human.

## Success Criteria *(mandatory)*

- **SC-009**: A file carrying the marker is never modified by repair or robustify, and its UUID is
  never used to resolve a link (provable by byte-diff + an unresolvable report).
- **SC-010**: A file that only shows the marker inside code is processed normally (SC for 002
  interplay).
- **SC-011**: Deterministic and idempotent as before.

## Assumptions

- The marker is a deliberate authoring/generator act; there is no need to auto-detect "generated"
  files heuristically.
- Removing a file from the graph is the safe direction; a link that becomes unresolvable because
  its target opted out is reported, never guessed.

## Constitution Check

- **I. Single responsibility** — ✅ still links + uuid only; this only selects which files play.
- **II. Safe by default** — ✅ strengthens safety; default behavior; skipped count is reported.
- **III. Plain, tool-agnostic, self-contained** — ✅✅ the opt-out lives *in the file*, no external
  index/config; an HTML comment readable everywhere. This is the principle's ideal.
- **IV. Deterministic, no AI** — ✅ pure textual match.
- **V. Test-first** — ✅ failing tests written before implementation.

No violations; no complexity-tracking entries. This generalizes the existing region-ignore
mechanism rather than special-casing, addressing the altitude concern from the 002 review.
