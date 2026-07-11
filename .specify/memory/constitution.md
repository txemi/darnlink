# darnlink Constitution

> darnlink — *auto-healing Markdown links*. Keeps Markdown links robust by anchoring them to a
> UUID: repairs links whose target moved, and upgrades plain links to robust ones.
> Name: *darn* (to mend) + *link*. Backronym: **D**eterministic **A**nchored **R**eference **N**etwork.

## Core Principles

### I. Single Responsibility — Links & UUIDs Only (NON-NEGOTIABLE)
darnlink does exactly one thing: keep Markdown links robust by anchoring them to a UUID. It
knows about Markdown files, links, and a `uuid` frontmatter field — nothing else. No entity
model, no issue/project management, no autogrid, no document semantics. Any feature that needs
to understand the *meaning* of a document is out of scope. Scope creep is the failure mode that
sank its predecessor (`tx_aiready_mdlink`, which began as robust links and became a heavy
project manager); it is refused by default.

### II. Safe by Default — Dry-Run First
The default invocation never writes; it reports what it *would* do. Mutating the filesystem
requires an explicit flag (`--write`). No interactive prompts, no `sys.exit()` in library code,
no surprise edits. Destructive operations are opt-in and announced. (Direct lesson from the
predecessor's "gate" incident, where mere indexing silently wrote to 264 files.)

### III. Plain, Self-Contained, Tool-Agnostic
The robust-link format is plain Markdown that renders anywhere: `[text](path) <!-- uuid: <uuid> -->`.
The link stays human-readable and clickable even when its path is stale. The UUID lives both in
the link and in the target's frontmatter — **no external database, no index file, no editor or
app lock-in**. A repository carrying darnlink links must remain fully usable without darnlink
installed. (This is the key differentiator from org-mode's `id:` links, which need a central
location database and the emacs app.)

### IV. Deterministic — No Heuristics, No AI
Repairs resolve by **exact UUID match** against frontmatter. Given the same tree, the output is
identical and reproducible. No fuzzy matching, no machine learning, no network calls. A
traditional, auditable algorithm a human can verify.

### V. Test-First & Acceptance-Driven
Behavior is defined by tests before implementation. The cornerstone acceptance test:
*rename/move a file that has N inbound robust links, run darnlink, and every link is repaired to
the new path — and nothing else in the tree changes.* If that passes, the tool works.

## The Two Operations (the scope boundary)
darnlink performs exactly two operations and no more:
1. **Robustify** — upgrade a correct-but-plain relative link to a robust link: ensure the target
   has a `uuid` in its frontmatter (add one *if missing*, because a link now references it — a
   UUID is created only when something needs it), and append `<!-- uuid: … -->` to the link.
2. **Repair** — fix a robust link whose path drifted: rewrite the path to the target located by
   its UUID.

## Technical Constraints
- **Language**: Python 3.13+, standard library + `python-frontmatter` only. No heavy/ML deps.
- **Distribution**: one command via `uvx`/`pipx` (`uvx darnlink …`); usable as a **pre-commit
  hook** and a **GitHub Action**.
- **Idempotent**: running twice changes nothing the second time.
- The **robust-link format is published as a small standalone spec** so others can adopt it
  without the tool.

## Development Workflow
- **Spec-Driven Development** (GitHub Spec Kit): Constitution → Specify → Plan → Tasks →
  Implement, each with a human checkpoint.
- **Frequent, small, reviewable commits.**
- Validate against a **disposable `/tmp` clone** of a real Markdown repo, never a live tree.
- **License**: **GPL-3.0-or-later** — copyleft, to keep evolutions open; may relax to a permissive
  license later if it helps adoption.

## Governance
This constitution governs scope and quality. Adding any capability beyond the two operations
requires explicitly amending Principle I and justifying why it cannot be a separate tool.
Simplicity and scope discipline win ties.

**Version**: 1.0.0 | **Ratified**: 2026-06-06 | **Last Amended**: 2026-06-06
