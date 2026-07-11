# Feature Specification: darnlink core — robustify & repair Markdown links

**Feature Branch**: `001-robustify-and-repair`

**Created**: 2026-06-06

**Status**: Draft

**Input**: A standalone, plain-Markdown tool that keeps internal links robust by anchoring them
to a UUID: it repairs links whose target file moved, and upgrades plain links to robust ones.
No database, no editor lock-in, dry-run by default. See `.specify/memory/constitution.md`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Repair links after a file moves (Priority: P1)

A doc author renames or moves a Markdown file that other files link to. The inbound links would
normally break. Running darnlink rewrites each robust link to the file's new location, found by
its UUID — so the links keep working with no manual fixing.

**Why this priority**: This is the core promise ("auto-healing") and the original reason the tool
exists. It alone delivers value even without robustify.

**Independent Test**: In a sample repo, give file B a `uuid` and a robust link from A to B; move B
to a new path; run `darnlink --write`; assert A's link now points to B's new path and resolves.

**Acceptance Scenarios**:

1. **Given** A contains `[text](old/B.md) <!-- uuid: U -->` and B's frontmatter has `uuid: U`,
   **When** B is moved to `new/B.md` and `darnlink --write` runs, **Then** A's link path becomes
   the correct relative path to `new/B.md`, the `<!-- uuid: U -->` annotation is unchanged, and no
   other bytes in A (or any file) change.
2. **Given** several files link to B by its UUID, **When** B moves and `darnlink --write` runs,
   **Then** all those links are repaired in one pass.
3. **Given** a robust link whose path is already correct, **When** darnlink runs, **Then** it makes
   no change (no-op).

---

### User Story 2 - Robustify plain links (Priority: P2)

A doc author has ordinary relative Markdown links and wants them to survive future moves. darnlink
upgrades a plain link to a robust one: it ensures the target file has a `uuid` in its frontmatter
(creating one only because a link now references it) and appends `<!-- uuid: … -->` to the link.

**Why this priority**: Turns an existing repo's links into self-healing ones. Valuable, but
secondary to repair (you can repair links that were robustified by hand, as we did manually).

**Independent Test**: Give A a plain `[text](rel/B.md)` that resolves to a local .md; run
`darnlink robustify --write`; assert B gained a `uuid` and A's link gained the matching annotation.

**Acceptance Scenarios**:

1. **Given** A has `[text](rel/B.md)` (plain, resolves) and B has no `uuid`, **When**
   `darnlink robustify --write` runs, **Then** B's frontmatter gains a fresh `uuid`, and A's link
   becomes `[text](rel/B.md) <!-- uuid: <B.uuid> -->`.
2. **Given** B already has a `uuid`, **When** robustify runs on a plain link to B, **Then** the
   existing `uuid` is reused (no new one), and the annotation is appended.
3. **Given** a link already robust, **When** robustify runs, **Then** no change (idempotent).

---

### User Story 3 - Safe report / dry-run (Priority: P1)

A user runs darnlink with no write flag to see exactly what it *would* do — which robust links are
broken (and where they'd be repaired to), which plain links could be robustified, and which links
are unresolvable — without modifying anything.

**Why this priority**: Safety is non-negotiable (Constitution II). The default must never write.
This is co-P1 with repair because it is how repair is used responsibly.

**Independent Test**: Run `darnlink` (no `--write`) over a repo; checksum all files before and
after; assert zero changes and a correct report.

**Acceptance Scenarios**:

1. **Given** any repo, **When** `darnlink` runs without `--write`, **Then** it prints a report and
   modifies zero files (verifiable by checksum).
2. **Given** broken/ambiguous/unresolvable links, **When** the report runs, **Then** each is listed
   with its file, the link, and what would happen (repair-to-path / robustify / cannot-resolve).

---

### Edge Cases

- **UUID not found** (robust link whose UUID is in no file's frontmatter): report as
  *unresolvable*; do not touch. (Target probably deleted.)
- **UUID ambiguous** (same UUID in >1 file's frontmatter): report as *ambiguous*; do not repair
  (never guess). Surfacing duplicates is itself useful.
- **Plain-link target without frontmatter at all**: on robustify (`--write`), create a minimal
  frontmatter block containing only `uuid`; if the file cannot take frontmatter, report and skip.
- **Fragment links** (`file.md#section` or bare `#section`): preserve the `#fragment` when
  repairing a path; bare `#section` (same-file anchors, no target file) are out of scope — ignored.
- **Non-local links** (http(s) URLs, mailto, links to non-`.md` files): ignored entirely.
- **Links inside code** (fenced blocks or inline code): ignored — they are examples, not
  navigational links. Refined in feature `002-ignore-code-blocks` (FR-015..FR-018).
- **Target moved AND its content changed**: repair only the link path; never touch content.
- **Multiple links in one line / multiple robust links in a file**: each handled independently.
- **Idempotency**: a second run after a `--write` run makes no further changes.
- **Relative path correctness**: the rewritten path must be correct relative to the *linking*
  file's directory (not the target's, not the repo root).
- **Files/dirs to skip**: respect git-ignored paths and a configurable exclude (e.g. `.git`,
  `node_modules`); never descend into them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: MUST detect robust links matching the grammar `[text](path) <!-- uuid: <uuid> -->`
  (UUID = standard 8-4-4-4-12 hex).
- **FR-002**: MUST build a `uuid → file` index by reading the `uuid` field from each Markdown
  file's YAML frontmatter.
- **FR-003** (repair): When a robust link's `path` does not point to the file whose frontmatter
  `uuid` equals the link's UUID, MUST rewrite `path` to the correct path relative to the linking
  file. The link text and UUID annotation are preserved.
- **FR-004** (robustify): MUST upgrade a plain relative link that resolves to a local `.md` into a
  robust link: ensure the target has a `uuid` (create one if absent), then append `<!-- uuid: … -->`.
- **FR-005** (safety): MUST NOT modify any file unless `--write` is given. Default = report only.
- **FR-006** (determinism): MUST resolve solely by exact UUID match — no fuzzy or heuristic
  matching, no network, no AI.
- **FR-007**: MUST report (not modify) unresolvable robust links (UUID absent) and ambiguous ones
  (UUID in >1 file).
- **FR-008**: MUST be idempotent (second run after write changes nothing).
- **FR-009**: MUST preserve link text and any `#fragment` when rewriting a path.
- **FR-010**: MUST leave non-local links (URLs, non-`.md`) untouched.
- **FR-011**: MUST create a UUID only where a link requires it (robustify); MUST NOT blanket-add
  UUIDs to files that nothing links to.
- **FR-012** (CLI): MUST expose a `darnlink` command operating over a path/dir (default: cwd),
  with at least: default report mode, `--write` to apply, and selectable operation
  (repair / robustify / both).
- **FR-013**: MUST exit 0 when there is nothing to fix (or in dry-run), non-zero when unresolved
  problems remain — usable as a CI / pre-commit / GitHub Action gate.
- **FR-014**: MUST be runnable as a single command with no config (`uvx darnlink …`).

### Key Entities

- **Robust link**: an inline Markdown link carrying both a human path and a machine UUID:
  `[text](path) <!-- uuid: <uuid> -->`.
- **Frontmatter UUID**: the `uuid` field in a file's YAML frontmatter — the anchor identity.
- **UUID index**: the in-memory map `uuid → file path` built from frontmatter; the sole basis for
  repair.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After moving any file with N inbound robust links and running `darnlink --write`,
  100% of those links resolve again, and the git diff touches only those link lines.
- **SC-002**: Running darnlink twice yields zero changes on the second run (idempotent).
- **SC-003**: In default (dry-run) mode, zero files change — provable by before/after checksums.
- **SC-004**: Tool installs and runs via a single `uvx darnlink …` command, no configuration.
- **SC-005**: A repository carrying darnlink links renders identically in any Markdown viewer (the
  UUID is an HTML comment, invisible) and remains usable with darnlink uninstalled.

## Assumptions

- Markdown files use YAML frontmatter; the anchor field is `uuid`.
- Links of interest are relative links to local `.md` files within the same tree.
- One UUID identifies one file; uniqueness is the author's responsibility — duplicates are
  reported, never auto-resolved.
- v1 scope is file-level links; heading-level anchors are preserved but not independently anchored.
- Python 3.13+ with `python-frontmatter`; no heavy dependencies (per Constitution).

## Reference implementation (predecessor) — what we copy

The robust-link mechanism already exists and works in `tx_aiready_mdlink` (the predecessor). We
take it as the reference and reuse its proven design rather than reinvent it:

- **Grammar** (`robust_links/pending_refactor/robust_uuid_utils.py`):
  `r"\[([^\]]+)\]\(([^)]+)\)\s*<!-- uuid: ([0-9a-f\-]{36}) -->"`. Detect with tolerant whitespace
  (`\s*`) between `)` and the comment; **emit** with a single space.
- **Repair algorithm** (`robust_links/repair/repair.py`, action `ACTUALIZAR_PATH`): locate the link
  by desc+href+uuid, recompute the path **relative to the linking file** via
  `get_relative_link_path(original, target_abs, md_file_abs, repo_root)`, substitute preserving
  `desc` and the uuid comment, write only if changed.
- **Resolution**: find the target by **exact UUID match** against frontmatter `uuid`.

## Resolved design decisions (deltas vs the reference)

1. **Comment placement** → as the reference: after `)`, detected with `\s*`, emitted with one space.
2. **Drop the entity machinery** → the reference resolves uuid→file through the heavy entity index
   (`csv_data_manager`/`MarkdownRepoIndex`, all of L2/L3). darnlink replaces it with a plain
   `uuid → file` dict built by scanning frontmatter. *(This is the whole point of the L1 split.)*
3. **No `sys.exit`, no prompts, dry-run default** → unlike the reference's `ValidationMode` +
   `input()` + `sys.exit`, darnlink is pure functions, report by default, `--write` to apply.
4. **Robustify aggressiveness** (NEW — the reference never upgraded plain→robust): `robustify` is an
   explicit command over a scope you pass; within that scope it upgrades all plain links that
   resolve to a local `.md`. Never the whole repo by surprise.
5. **Creating frontmatter where none exists** → the reference did this in bulk (caused the
   264-file incident); darnlink keeps the capability but **opt-in** (`--create-frontmatter`), off
   by default, and always under `--write` + dry-run preview.
