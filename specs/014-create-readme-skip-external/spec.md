# Feature Specification: `--create-readme` skips folders holding downloaded/external content

**Feature Branch**: `014-create-readme-skip-external`

**Created**: 2026-07-22

**Status**: Draft

**Input**: `--create-readme` (feature 012) can be pointed at a documentation tree that also contains a
**mirror** of external systems (captured chats, downloaded documents, exported issues). A link from an
authored file into a capture folder would make darnlink create a `README.md` **inside that capture**,
injecting a darnlink anchor into content we do not own. `--exclude` is too coarse — it also drops the
folder's *authored* management files (our READMEs, `analysis.md`) from robustification.

## Motivation

The rule a real tree wants is by **provenance**, not location: *robustify everything we authored;
never touch what was downloaded.* darnlink already has the per-file `<!-- darnlink-ignore-file -->`
marker (a downloaded/generated file carries it → it is neither source nor target). This feature lets
that same marker also answer the directory-level question `--create-readme` asks: **is this folder
ours, or the mirror's?** A folder that holds a downloaded file is the mirror's, so no README is created
there — while the folder's authored files are still robustified, and folders elsewhere are unaffected.

This is the surgical alternative to `--exclude mirror`: it keeps our management files inside the mirror
anchorable and only skips the actual downloaded captures.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Don't create a README inside a downloaded capture (Priority: P1)

An authored note links to a captured chat folder that holds a `transcript.md` marked
`<!-- darnlink-ignore-file -->`. With `--create-readme`, darnlink does **not** create a README there.

**Acceptance Scenarios**:

1. **Given** `capture/transcript.md` carries `<!-- darnlink-ignore-file -->` and `A.md` links
   `[cap](capture/)`, **When** `--create-readme` runs, **Then** no README is created in `capture/` and
   nothing is written.
2. **Given** a folder `hub/` with only an authored `notes.md` (no marker) that `A.md` links to,
   **When** `--create-readme` runs, **Then** `hub/README.md` **is** created (the folder is ours).
3. **Given** an empty folder `hub/` (no `.md` at all) that `A.md` links to, **When** `--create-readme`
   runs, **Then** `hub/README.md` **is** created — the signal is the *presence* of a marked file, so an
   empty hub is not mistaken for external content.

## Requirements *(mandatory)*

- **FR-014a**: `--create-readme` does not create a `README.md` in a target directory that **directly**
  contains a `.md` file carrying `<!-- darnlink-ignore-file -->`.
- **FR-014b**: The check is a *positive* signal (a marked file must be present). A folder with no such
  file — empty, or holding only authored `.md` — is unaffected.
- **FR-014c**: Only the target directory's own direct children are inspected (not recursively): a
  capture folder holds its downloaded files directly; a parent folder is judged by its own contents.
- **FR-014d**: Composes with the existing guards (`--exclude`, `--only`, `--no-create-frontmatter-for`,
  the root boundary) — any one of them still skips creation independently.

## Out of Scope

- Marking the downloaded files themselves (that is the consumer's ingest pipeline; darnlink only reads
  the marker). A repo adopts this by ensuring its downloaded/generated `.md` carry
  `<!-- darnlink-ignore-file -->`.
- A recursive scan of the target subtree, or a directory-level marker file — the direct-child `.md`
  check covers the capture-folder case without either.
