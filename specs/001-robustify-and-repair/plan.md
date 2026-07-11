# Implementation Plan: darnlink core — robustify & repair

**Branch**: `001-robustify-and-repair` | **Date**: 2026-06-06 | **Spec**: `./spec.md`

**Input**: `specs/001-robustify-and-repair/spec.md` + `.specify/memory/constitution.md`

## Summary

A small, dependency-light Python CLI/library that keeps Markdown links robust by anchoring them to
a UUID. Two operations: **repair** (rewrite a robust link's path to wherever its UUID now lives) and
**robustify** (upgrade a plain link to a robust one). Default is a read-only report; `--write`
applies. The robust-link grammar and the path-recompute algorithm are **ported from the predecessor**
(`tx_aiready_mdlink`), but the heavy entity model is replaced by a plain `uuid → file` index — that
substitution is the entire point of the L1 split.

## Technical Context

**Language/Version**: Python 3.13+
**Primary Dependencies**: `python-frontmatter`; stdlib (`re`, `pathlib`, `argparse`, `uuid`, `os`). No ML/heavy deps.
**Storage**: N/A — operates directly on `.md` files; no database, no index file on disk.
**Testing**: `pytest`.
**Target Platform**: Linux/macOS CLI (cross-platform; pure Python).
**Project Type**: single project — library + CLI.
**Performance Goals**: scan thousands of `.md` in a couple of seconds; deterministic.
**Constraints**: dry-run by default, idempotent, zero config, no network, no `sys.exit` in lib code.
**Scale/Scope**: repos up to ~10k Markdown files (tested on a ~2.7k-file monorepo).

## Constitution Check

*GATE: must pass before and after design.*

- **I. Single responsibility (links+uuid only)** — ✅ modules only know links, frontmatter `uuid`, paths.
- **II. Safe by default (dry-run)** — ✅ writes only behind `--write`; report mode is the default; no prompts.
- **III. Plain, tool-agnostic** — ✅ link is an HTML comment; no DB/index file; works with tool uninstalled.
- **IV. Deterministic, no AI** — ✅ exact UUID match; no fuzzy/network.
- **V. Test-first & acceptance-driven** — ✅ acceptance test (move → repair all) is the first test written.

No violations; no complexity-tracking entries needed.

## Project Structure

### Documentation (this feature)
```text
specs/001-robustify-and-repair/
├── spec.md          # requirements (done)
├── plan.md          # this file
├── data-model.md    # Phase 1 (RobustLink, FrontmatterIndex)
├── quickstart.md    # Phase 1 (install + the 2 commands)
└── tasks.md         # Phase 2 (/speckit-tasks)
```

### Source code (repository root)
```text
src/darnlink/
├── __init__.py
├── links.py             # robust-link grammar: detect / parse / emit (ROBUST_LINK_RE, from reference)
├── frontmatter_index.py # scan tree -> {uuid: path}; detect duplicates (ambiguous)
├── paths.py             # get_relative_link_path(): path relative to the LINKING file (ported)
├── repair.py            # repair op: recompute path for robust links by UUID
├── robustify.py         # robustify op: plain link -> robust (+ ensure/create uuid)
├── report.py            # Finding model + collect (would-repair / robustify / unresolvable / ambiguous)
└── cli.py               # argparse: default report; repair / robustify subcommands; --write
tests/
├── unit/                # grammar regex, path calc across dirs, index + dup detection
├── integration/         # repair/robustify over a temp tree
└── acceptance/          # SC-001 move-and-repair; SC-002 idempotency; SC-003 dry-run zero-write
pyproject.toml           # package darnlink; entry point: darnlink = darnlink.cli:main
README.md
```

## Phase 0 — Research (minimal; the reference already did it)

- **Port, don't reinvent**: lift the grammar regex from `robust_uuid_utils.py` and the
  path-recompute from `repair.py` + `common_utils/path_utils.get_relative_link_path`. Decision:
  copy the *logic*, drop the entity coupling (no `RobustMdLink`, no `csv_data_manager`).
- **UUID detection**: keep the lenient `[0-9a-f-]{36}` for *matching*; always emit fresh `uuid4()`
  when *creating*.
- **Frontmatter**: `python-frontmatter` (same lib the reference implementation already uses) for read; for
  writing, render content before opening the file (avoid the truncation bug seen in the predecessor).

## Phase 1 — Design

### Data model (`data-model.md`)
- **RobustLink**: `text`, `href` (as written), `uuid`, plus match span `(start, end)` and the source
  file. Built by `links.find_robust_links(content)`.
- **PlainLink**: `text`, `href`, span — a Markdown link with no uuid comment, pointing to a local `.md`.
- **FrontmatterIndex**: `{uuid -> Path}` + `{uuid -> [Path,...]}` for duplicates; built once per run.
- **Finding**: `kind` (repair / robustify / unresolvable / ambiguous / created-frontmatter), file,
  link, old→new (for repair), reason. The report is a list of Findings.

### Core algorithms
- **Index**: walk tree (skip git-ignored + excludes), `frontmatter.load` each `.md`, map `uuid -> path`;
  collect duplicates separately.
- **Repair** (per file): for each robust link, resolve target by `index[uuid]`.
  - uuid missing → Finding(unresolvable); skip.
  - uuid ambiguous (in dup set) → Finding(ambiguous); skip (never guess).
  - else compute `new = get_relative_link_path(target, linking_file)`; if differs from `href`,
    Finding(repair, old→new); on `--write`, substitute (preserve `text` + ` <!-- uuid: X -->`).
- **Robustify** (per file, explicit scope): for each plain link to a local `.md` that resolves:
  - target has `uuid` → reuse it.
  - target has frontmatter but no `uuid` → add `uuid: <uuid4>` (on `--write`).
  - target has NO frontmatter → only with `--create-frontmatter`; else Finding(skipped-no-frontmatter).
  - append ` <!-- uuid: X -->` to the link (on `--write`).
- **Idempotency**: re-running finds nothing to change (a robust+correct link is skipped; a plain link
  already robustified is no longer "plain").

### Contracts (`quickstart.md` + CLI)
```
darnlink [PATH]                          # default: dry-run report (repair + robustify candidates)
darnlink repair [PATH] --write           # apply path repairs
darnlink robustify [PATH] --write [--create-frontmatter]
```
Exit code: 0 = nothing unresolved (or dry-run); non-zero = unresolved/ambiguous remain (CI gate).
Output: human-readable by default; `--json` for machine/CI consumption (later).

### Re-check Constitution after design
Still ✅ on all five. The `uuid → file` dict keeps it L1-only; dry-run + render-before-write keep it safe.

## Phase 2 — Tasks (out of scope here; `/speckit-tasks`)
Test-first order: grammar + path-calc unit tests → index → repair → robustify → CLI →
acceptance (move-and-repair, idempotency, dry-run-zero-write) → packaging (pyproject, uvx) →
pre-commit hook + GitHub Action.

## Validation strategy
- Develop/run tests against synthetic temp trees (pytest tmp_path).
- Smoke-test against a **disposable `/tmp` clone** of a real repo, never a live tree.
- Acceptance gate (SC-001..005) must pass before any `--write` is offered as "stable".

## Complexity Tracking
None. The design is deliberately minimal (Constitution I/VII).
