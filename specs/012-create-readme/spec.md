# Feature Specification: `--create-readme`

**Feature Branch**: `012-create-readme`

**Created**: 2026-07-22

**Status**: Draft

**Input**: Directory links (feature 011) can only be anchored when the folder already has a
`README.md` with a uuid. A link to a folder that has **no** README is left plain and unprotected.
Let an opt-in flag create that `README.md` so the link can be anchored — without weakening the
default "never creates files" guarantee.

## Motivation

Feature 011 protects links to folders that carry a `README.md` hub. But plenty of linked folders have
none, and for those the directory link stays plain and breaks silently on a move — the exact gap 011
set out to close, still open for README-less folders. Creating the README is the only thing that makes
such a folder anchorable (a directory cannot hold frontmatter itself).

This is deliberately **opt-in and separate** from `--create-frontmatter`. `--create-frontmatter`
promises to *edit existing files only* (insert a frontmatter block) and never to create files; folding
README creation into it would break that promise for everyone already relying on it. So README
creation gets its own flag.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Anchor a folder that has no README (Priority: P1)

A doc links to a folder (`docs/hub/`) that has no `README.md`. With `--create-readme`, darnlink
creates `docs/hub/README.md` — with a fresh uuid and a `# hub` heading — and anchors the link to it.

**Acceptance Scenarios**:

1. **Given** `A.md` has a plain `[hub](hub/)` and `hub/` exists without a `README.md`, **When**
   `--robustify --create-readme --write` runs, **Then** `hub/README.md` is created with a `uuid` and a
   `# hub` heading, and A's link gains ` <!-- uuid: … -->` with that uuid (path unchanged).
2. **Given** the same, **When** it runs **without** `--write`, **Then** nothing is written; the
   report names the README that would be created (`create_readme` finding).
3. **Given** several links (in one or more files) point at the same folder, **When** it runs, **Then**
   exactly **one** README is created and every link is anchored to it.
4. **Given** a created directory link is later moved, **When** repair runs, **Then** it heals like any
   other directory link (feature 011).

### Edge Cases

- **The folder does not exist.** darnlink creates a README *inside an existing directory only* — never
  the directory. A link to a non-existent path is left plain.
- **The folder already has a README.** No creation; the existing README's uuid is used (created only if
  it lacks one, because `--create-readme` implies `--create-frontmatter`).
- **`README.md` is deny-listed** (`--no-create-frontmatter-for README.md`): never created.
- **`--only` write scope**: a README is created only when it falls inside the write scope.

## Requirements *(mandatory)*

- **FR-012a**: `--create-readme` (plan flag `create_readme`) is **off by default**. When off, behavior
  is exactly feature 011 (a folder with no README → link left plain).
- **FR-012b**: When on, for each plain link to an **existing** directory with no `README.md` (in the
  write scope, not deny-listed), darnlink creates `<dir>/README.md` containing a fresh `uuid` and a
  `# <dirname>` heading, and anchors the link to that uuid.
- **FR-012c**: darnlink never creates the directory itself, only a README inside one that already
  exists.
- **FR-012d**: At most one README is created per directory, regardless of how many links point at it.
- **FR-012e**: Creation is dry-run by default (planned and reported); it is applied only with
  `--write`, like every other darnlink write.
- **FR-012f**: `--create-readme` implies `--create-frontmatter` (a run willing to create a README is
  willing to add a uuid to an existing one).
- **FR-012g**: A README is never created inside an `--exclude`'d subtree. `--exclude` prunes those
  directories from the scan, but a link from an *included* file can point at a directory *inside* an
  excluded one (a mirror, a vendored clone); creation must honor the exclusion for the write target,
  not only for the scan.

## Out of Scope

- Any content in the created README beyond the frontmatter uuid and a `# <dirname>` heading.
- Creating directories, or any file other than `README.md`.
- A different directory-identity file (e.g. `index.md`) — see spec 011 Out of Scope.
