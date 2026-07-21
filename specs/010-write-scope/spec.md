# Feature Specification: write scope — `--only`

**Feature Branch**: `010-write-scope`

**Created**: 2026-07-21

**Status**: Draft

**Input**: A contributor can run darnlink over the whole repo, or over a subtree — and neither serves
the commonest case: *"anchor the links in the file I am committing, and touch nothing else."*
Repo-wide `--robustify --write` rewrites every robustifiable link in the tree (in a consumer repo,
679 of them, most belonging to other people's work in flight); scoping the scan to a subtree instead
silently fails to anchor anything whose **target** lives outside that subtree. There is no way to say
*"read everything, write here"*.

## The two scopes (and why they are fused today)

Feature 006 split the two **axes** a file sits on (source / target). This feature splits the two
**scopes** an invocation has, which the positional `path` currently fuses into one:

| Scope | Question | Today |
|---|---|---|
| **Index scope** | Which files may be *read* — as link sources, and as targets whose `uuid` resolves? | `path` |
| **Write scope** | Which files may be *modified*? | `path` |

One knob answers both, so the two useful configurations are unreachable: narrowing the write scope
also blinds the index, and keeping the index whole also opens the write scope to the whole tree. The
first is not a theoretical loss — it is the failure below.

## Evidence this gap is real (not hypothetical)

The consumer repo `project_map` (~8.000 `.md`, ~15.000 Markdown links) runs a fail-closed pre-commit
gate: a commit is refused when a **staged** file carries a robustifiable plain link. Its advice to the
contributor is `darnlink <your/path> --robustify --write`, and on 2026-07-21 that advice could not be
followed:

- **Scoped to the author's directory**, the link's target lived in another subtree, so it was never
  indexed. The finding came back as `no frontmatter; target skipped` — while the target *did* have
  frontmatter and a `uuid`. The diagnosis was not merely unhelpful, it was **wrong** (see FR-009).
- **Repo-wide**, the run would have rewritten 679 links across other sessions' files and generated
  documents. The gate's own comment records that this already dirtied the repo three times
  (2026-06-11, 07-16, 07-17).

The link was anchored **by hand**, pasting `<!-- uuid: … -->` into the file. A tool whose entire job
is to write that comment lost to a text editor, because it could not be told *where it may write*.

## Why `--only`, and not "let `path` accept files"

The obvious shape is to let the positional accept `.md` files. It is rejected:

- **It says something false.** `darnlink some/file.md` reads as *"look at this file"*. darnlink cannot
  work that way: it must still walk the tree to build the `uuid → path` index (repair) and to read the
  targets' frontmatter (robustify). Nothing is skipped — a scoped run reads exactly as much as a full
  one. The saving is in *blast radius*, not in work, and the interface should not pretend otherwise.
- **It drags in `--root`.** Once the positional is a file, the index needs its own root — which means a
  new flag, or auto-detecting the git root, i.e. **git knowledge inside a tool that today knows only
  `.md` files, links and frontmatter** (Principle I/III).
- **It complicates a working contract.** `path` stays a directory, `not a directory` stays an error,
  every existing invocation and the pre-commit hook's `pass_filenames: false` stay literally true.

`--only` is a filter on the write scope and nothing else. It composes with the scan flags rather than
competing with them, and it reads as what it does: *scan from here, write only there*.

## Constitution Check

- **P-I (Links & UUIDs Only, NON-NEGOTIABLE):** refines *which files may be written*, the same class
  of knob as `--exclude` (which files are scanned) and the in-file markers (which axes a file joins).
  No document semantics, no external state, no VCS. In-bounds; no amendment needed. ✅
- **P-II (Safe by Default — Dry-Run First):** strictly *narrowing*. The default (no `--only`) is
  unchanged, and the flag can only ever reduce the set of files written. ✅
- **P-III (Self-Contained, Tool-Agnostic):** a CLI argument; nothing is stored, no config file, no git.
  A list produced by any means can be piped in (FR-002). ✅
- **P-IV (Deterministic):** output stays a pure function of (tree, flags). No heuristics, no inference
  of "what the user probably meant". ✅
- **P-V (Test-First):** the guarantee that makes the feature worth having — *nothing outside the write
  scope changes* — is an acceptance test, not a claim (Acceptance 3).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `--only PATH` (repeatable) MUST restrict **writes** to the named `.md` files. It MUST NOT
  affect which files are scanned, indexed, or reported on.
- **FR-002**: `--only-from FILE` MUST read newline-separated paths from FILE, where `-` means stdin, so
  a list produced elsewhere composes without darnlink learning where it came from. `--only` and
  `--only-from` MUST be combinable (union).
- **FR-003**: Every path given MUST exist, be a `.md` file, and resolve **inside** the scanned root; any
  other path is a usage error (exit 1) naming the offending path. Silently ignoring an unmatched path
  would turn a typo — or a stale entry in a generated list — into a green run that wrote nothing.
- **FR-004**: With `--robustify --write`, a plain link in a file in the write scope MUST be annotated
  exactly as it would be in a full-tree run, **including when its target lives outside the scope** —
  the target's `uuid` is read from the index, which `--only` does not narrow (FR-001). This is the
  motivating failure and the feature's reason to exist.
- **FR-005**: With `--write` (repair), a robust link in a file in the write scope whose target moved
  MUST be repaired exactly as in a full-tree run.
- **FR-006**: Writing a `uuid` into a **target's** frontmatter is the one write allowed outside the
  scope, because a link cannot be anchored to a target that has no `uuid`. It MUST be announced by
  path in the report, in human and `--json` output, before it happens (dry-run) and when it happens.
  `--no-target-writes` MUST suppress it: the link is then left plain and reported with the existing
  "target has no uuid" kind, so a caller that needs the hard guarantee can have it.
- **FR-007**: No file outside `--only` ∪ (targets receiving a `uuid` per FR-006) may be modified. This
  is the guarantee the feature exists to provide; it MUST hold for every operation and flag combination.
- **FR-008**: A repair run narrowed by `--only` MUST state, in its report, that only **outbound** links
  were considered and that a moved target still requires a full-tree run to fix its **inbound** links.
  A narrowed run can only ever see the links written *inside* the scoped files; a clean result is not
  evidence of a clean tree, and must not read like one.
- **FR-009** *(adjacent fix, same confusion)*: A link whose target is **outside the scanned root** MUST
  be reported with its own kind — distinct from the target having no frontmatter. Today both collapse
  into `no frontmatter`, which states as fact something the run never checked and cannot know.
- **FR-010**: `darnlink check` MUST accept `--only` and restrict its **findings** to links whose source
  file is in the set (it writes nothing, so there is no write scope to narrow). Exit-code semantics are
  unchanged. This is what a pre-commit gate needs: *is what I am committing clean?*
- **FR-011**: Without `--only`/`--only-from`, behaviour MUST be byte-identical to today, for every
  operation (regression: the positional keeps meaning "root directory to scan").
- **FR-012**: Runs MUST stay idempotent: a second run with the same `--only` set changes nothing.

### Key Entities

- **Write scope**: the set of files an invocation may modify. Defaults to the index scope (today's
  behaviour); `--only` narrows it. Not persisted anywhere — an argument, alive for one run.

## Acceptance

1. **The motivating case.** `A.md` (in `x/`) holds a plain link to `B.md` (in `y/`), which has a `uuid`.
   `darnlink . --robustify --write --only x/A.md` anchors the link in `A.md` and leaves the rest of the
   tree byte-identical. (Today's alternatives: `darnlink x/` skips it as "no frontmatter"; `darnlink .`
   rewrites the whole tree.)
2. **Several files at once.** Two files, each with links into unrelated subtrees, are both anchored in
   one run; nothing else changes.
3. **The guarantee.** In a tree with many robustifiable links, a `--only` run modifies exactly the
   scoped files (plus any target receiving a `uuid`, each named in the report) and no other file —
   verified by hashing the tree before and after.
4. **Target writes are visible and refusable.** A target with frontmatter but no `uuid` is named in the
   dry-run report; with `--no-target-writes` it is not written, and the link is left plain and reported.
5. **Repair, narrowed.** A file whose robust link went stale is repaired via `--only`; the report says
   inbound links elsewhere were not considered.
6. **Guard rails.** `--only` with a non-existent path, a non-`.md` path, or a path outside the root
   exits 1 naming it.
7. **Piped list.** The same set passed via `--only-from -` behaves identically to repeated `--only`.
8. **Regression.** Every existing invocation without `--only` produces identical output and identical
   writes; `darnlink some/file.md` still fails with `not a directory`.

## Out of scope

- **A `--staged` flag.** darnlink must not learn about git (P-I/P-III). Once `--only-from -` exists it
  is one line in a consumer's hook or in `recipes/`:
  `git diff --cached --diff-filter=ACMR --name-only -- '*.md' | darnlink . --robustify --write --only-from -`.
  A recipe is the right home: it is where the VCS knowledge already lives.
- **Auto-staging what was written.** A tool that edits files must not touch the git index; the caller
  re-adds. (A hook that fixes files must also decide whether to re-run — that is the hook's policy.)
- **Reading staged blobs instead of the worktree.** darnlink reads the worktree, as it always has. A
  file with unstaged modifications is anchored as it exists on disk; the caller owns that trade-off.
- **Inbound links.** No index of "who links to this file" is added — it would be an external index
  (P-III). Full-tree runs remain the way to repair a moved target's inbound links, which is what the
  consumer gate and CI already enforce.
- **Allowlists of files never to write** (globs a consumer wants darnlink to leave alone). That need is
  already served on the file's own terms by `<!-- darnlink-ignore-links -->` (006); `--only` is a
  per-invocation narrowing, not a repo policy.
