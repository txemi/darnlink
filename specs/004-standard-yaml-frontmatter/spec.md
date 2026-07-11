# Feature Specification: read uuid with a standard YAML parser; report invalid frontmatter

**Feature Branch**: `004-standard-yaml-frontmatter`

**Created**: 2026-06-08

**Status**: Draft

**Input**: darnlink currently reads a target's `uuid` two different ways: the index/repair path uses
a real YAML parser (`python-frontmatter` / PyYAML), while the robustify path uses a tolerant regex
(`read_uuid_from_content`). On a file whose frontmatter is **invalid YAML**, the regex silently
*accepts* it (robustify anchors a link to its uuid) but the YAML parser *rejects* it (the index
cannot resolve that uuid). Result: robust links that no operation can repair, and invalid data
accepted in silence. This was found in the field (a `purpose:` value containing `: ` broke YAML).

This feature makes **reading deterministic and standard**: one canonical YAML-based reader used
everywhere, and **invalid frontmatter is reported as an error**, never silently accepted or skipped.

## Why standard YAML (not tolerant regex)

The robust-link format anchors identity in **YAML frontmatter** (FORMAT.md). The authority on whether
frontmatter is well-formed is a standard YAML parser, not a hand-rolled regex. A regex that accepts
what YAML rejects is the worst case: the tool contradicts itself and lets malformed data through.
Using PyYAML everywhere makes behavior predictable, matches the published format, and surfaces bad
data so the author fixes it — instead of darnlink quietly papering over it.

Note on writing: inserting the `uuid:` line stays **surgical** (textual, no YAML re-dump) to avoid
reordering keys / the truncation bug of the predecessor — but it is only performed on files whose
frontmatter is valid (or absent). Reading and validation are YAML; writing is surgical-but-gated.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Invalid frontmatter is reported, never silently accepted (Priority: P1)

A target file has frontmatter that is not valid YAML. darnlink must NOT read a uuid from it, must NOT
write into it, and must **report it** so the author fixes the data.

**Acceptance Scenarios**:

1. **Given** `B.md` whose frontmatter is invalid YAML (e.g. an unquoted value containing `: `),
   **When** `darnlink --robustify --write` runs and `A.md` links to `B.md`, **Then** `B.md` is NOT
   modified, no uuid is created for it, `A.md`'s link is left plain, and a finding of kind
   `invalid_frontmatter` names `B.md`.
2. **Given** the same `B.md` carries a `uuid` line inside its invalid YAML, **When** `build_index`
   runs, **Then** that uuid is **not** indexed and `B.md` is recorded as invalid (reported).
3. **Given** any run encounters ≥1 invalid-frontmatter file, **When** it finishes, **Then** the exit
   code is non-zero and the report lists the invalid files (so it works as a CI gate).

---

### User Story 2 - Consistent reading across operations (Priority: P1)

The uuid that robustify reads/reuses and the uuid the index resolves MUST come from the same parser,
so a link robustify created always resolves in repair (no "unresolvable" for valid data).

**Acceptance Scenarios**:

1. **Given** `B.md` with valid frontmatter `uuid: U`, **When** robustify reuses it and repair later
   resolves a link to it, **Then** both read exactly `U` (same canonical YAML reader). No divergence.
2. **Given** a tree with only valid frontmatter, **When** robustify then repair run, **Then** zero
   `unresolvable` findings (every robustified link resolves).

---

### Edge Cases

- **No frontmatter at all**: unchanged behavior — robustify creates a minimal block only under
  `--create-frontmatter`; otherwise reports `no_frontmatter` and skips. (Distinct from *invalid*.)
- **Valid frontmatter, no `uuid`**: unchanged — a uuid line is surgically inserted (valid YAML stays
  valid: a new top-level key after the opening `---`).
- **Invalid frontmatter**: reported `invalid_frontmatter`; never read, never written, never indexed.
- **`uuid` present but value not a string / not a scalar**: treated as no usable uuid (reported as
  invalid or no-uuid; never guessed).
- **Source file with invalid frontmatter**: its *links* can still be detected (link scanning is
  independent of frontmatter), but it is never given a uuid and is reported if it would need one.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-023**: uuid reading MUST use a single canonical YAML parser (`python-frontmatter` / PyYAML)
  across ALL operations (index, repair, robustify). The tolerant regex reader MUST NOT be used to
  read uuids for resolution decisions.
- **FR-024**: Frontmatter that is present but not valid YAML MUST be classified `invalid` and
  reported (`Kind.INVALID_FRONTMATTER`); it MUST NOT be read for a uuid, MUST NOT be indexed, and
  MUST NOT be written to.
- **FR-025**: Writing the `uuid:` line MUST remain surgical (no YAML re-dump) and MUST only happen on
  files whose frontmatter is valid or absent (gated by FR-024).
- **FR-026**: A run that encounters ≥1 invalid-frontmatter file MUST report them (human + `--json`)
  and exit non-zero (CI gate), in addition to its normal output.
- **FR-027**: For valid data, robustify and repair MUST agree on every uuid (no spurious
  `unresolvable`) — i.e. the consistency the two-reader split previously broke.

## Success Criteria *(mandatory)*

- **SC-012**: A file with invalid YAML frontmatter is never modified, never indexed, and is reported;
  exit code non-zero.
- **SC-013**: On a tree of only valid frontmatter, robustify-then-repair yields zero `unresolvable`.
- **SC-014**: Deterministic & idempotent unchanged.

## Assumptions

- `python-frontmatter` (already a dependency) wraps PyYAML; YAML errors surface as exceptions we
  classify as `invalid`.
- Surgical insertion of a single `uuid:` line into a valid (or empty) frontmatter block keeps it
  valid YAML.

## Constitution Check

- **I. Single responsibility** — ✅ still links + uuid; this fixes how uuid is read/validated.
- **II. Safe by default** — ✅ strengthens safety: invalid data is reported, not silently accepted or
  written; default behavior.
- **III. Plain, tool-agnostic** — ✅ no format change; uses the standard YAML the format already
  specifies.
- **IV. Deterministic, no AI** — ✅ removes a tolerant-regex heuristic in favor of the standard
  parser; one canonical reader → reproducible.
- **V. Test-first** — ✅ failing tests for invalid-frontmatter reporting + read consistency first.

No violations. This resolves a self-inconsistency (two readers) rather than adding a capability.
