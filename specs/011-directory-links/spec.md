# Feature Specification: directory links

**Feature Branch**: `011-directory-links`

**Created**: 2026-07-22

**Status**: Draft

**Input**: Robust links can only target `.md` files, so a link to a *directory* (`docs/guide/`) is
invisible to darnlink: it is never robustified and silently breaks when the directory moves. Let a
directory be a first-class link target, identified by the `uuid` of its `README.md`.

## Motivation

darnlink heals `.md`→`.md` links, but real doc trees link to **directories** too — "see the
[deployment guide](ops/deploy/)", a hub folder, a country's report folder. Those links are outside
the tool: move or rename the folder and they die with no warning, and no `--robustify`/gate can
protect them. A directory already tends to carry a `README.md` hub with a `uuid`; that uuid is a
perfectly good stable identity for the directory. This feature uses it.

Measured on one real tree at adoption time: of the directories linked from a refactored subtree, a
clear majority already had a `README.md` with a uuid — i.e. this feature would have protected them
automatically, where nothing could before.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Repair a directory link after the directory moves (Priority: P1)

A doc links to a directory as `[guide](docs/guide/)`; the link is robust (carries the uuid of
`docs/guide/README.md`). Someone moves `docs/guide/` to `manuals/guide/`. Running darnlink rewrites
the link's path to the directory's new location — found by the README's uuid — keeping it a
directory link.

**Independent Test**: robust directory link to `docs/guide/`; move the directory; `darnlink --write`;
assert the path is now `manuals/guide/` and still resolves.

**Acceptance Scenarios**:

1. **Given** `A.md` contains `[guide](docs/guide/) <!-- uuid: U -->` and `docs/guide/README.md` has
   `uuid: U`, **When** the directory moves to `manuals/guide/` and `darnlink --write` runs, **Then**
   A's link path becomes `manuals/guide/` (a directory path), the uuid is unchanged, and nothing else
   changes.
2. **Given** a robust directory link whose path already points at the right directory, **When**
   darnlink runs, **Then** it is a no-op — regardless of a trailing slash.
3. **Given** a directory link written without a trailing slash, **When** it is repaired, **Then** the
   emitted path carries a trailing slash (canonical directory form).

### User Story 2 - Robustify a plain directory link (Priority: P2)

A plain link `[guide](docs/guide/)` points at a directory whose `README.md` has (or, with
`--create-frontmatter`, can be given) a uuid. darnlink upgrades it to a robust link anchored to that
uuid.

**Acceptance Scenarios**:

1. **Given** `docs/guide/README.md` has `uuid: U` and `A.md` has a plain `[guide](docs/guide/)`,
   **When** `darnlink --robustify --write` runs, **Then** the link gains ` <!-- uuid: U -->` and its
   path is unchanged.
2. **Given** the directory's `README.md` has no uuid, **When** `--robustify` runs without
   `--create-frontmatter`, **Then** the link is left plain and reported (`no_frontmatter`); **with**
   `--create-frontmatter`, a uuid is created **in the existing README** and the link is anchored.
3. **Given** a directory with **no** `README.md`, **When** `--robustify --create-frontmatter` runs,
   **Then** the link is left plain — darnlink never creates a README.

### Edge Cases

- **Path/uuid disagreement (conflict).** A directory link whose old path still resolves to a real
  *different* directory, while the README lives elsewhere, is a conflict: left untouched, reported.
- **Directory link anchored to a non-README uuid.** Malformed (the path names a directory but the
  uuid is some other file): conflict, left untouched.
- **File link to a `README.md`.** Unchanged behavior: `[x](docs/guide/README.md) <!-- uuid: U -->`
  still repairs to the *file* path, never the directory. The `.md` suffix is the discriminator.

## Requirements *(mandatory)*

- **FR-011a**: A link whose path part does **not** end in `.md` and that resolves to a directory is a
  *directory link*; its anchor file is `<dir>/README.md`.
- **FR-011b**: Classification of file vs directory link is by the href path suffix alone — no disk
  access — so it is deterministic and stable even when the path is stale.
- **FR-011c**: Repair of a directory link rewrites to the README's **parent directory**, relative to
  the linking file, emitted with a trailing slash. Text, fragment and uuid are preserved.
- **FR-011d**: Robustify anchors a plain directory link to its README's uuid, honoring
  `--create-frontmatter`, `--no-create-frontmatter-for`, `--only` and the ignore markers exactly as
  for file targets. A directory without a `README.md` is not anchorable.
- **FR-011e**: A directory link is never reported as a CONFLICT merely because its path resolves to a
  directory; conflict applies only when path and uuid genuinely disagree (real different directory at
  the old path, or the uuid belongs to a non-README file).

## Out of Scope

- Creating a `README.md` where none exists (darnlink only creates frontmatter, never files).
- A distinct finding for "directory link, no README" — such a link is simply left plain, like any
  other non-anchorable target. (Possible future refinement for a stricter gate.)
- Directory identity via anything other than `README.md` (e.g. `index.md`, an `.uuid` dotfile).
