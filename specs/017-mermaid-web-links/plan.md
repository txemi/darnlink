# Implementation Plan: see web links inside `mermaid` diagrams (read axis only, opt-in)

**Branch**: `017-mermaid-web-links` | **Date**: 2026-08-23 | **Spec**: `spec.md`, same directory

**Input**: Feature specification from `specs/017-mermaid-web-links/spec.md`

## Summary

Let the **read** axes see the destinations carried by a diagram's `click` directives, which today
are invisible because they sit inside a fenced region (feature 002). The region computation is
**reused, not re-implemented**; the destination is recognised by a pure textual function over three
measured one-line shapes; recognised items enter the existing web axis in its existing shape, so
classification, exit codes and feature 016's own-repository strictness apply with no special case.
The feature is **off by default**, per repository, and its items are **report-only** — they can
never be anchored, because the anchor is an HTML comment and a diagram would render it as content.

## Technical Context

**Language/Version**: Python 3.13+ (floor declared 3.10 in packaging metadata)

**Primary Dependencies**: **none added.** Runtime stays `python-frontmatter` only, per the
constitution's *Technical Constraints*. See `research.md` R1 for the three alternatives measured
and rejected.

**Storage**: N/A — the tool holds no state; the only persistence is the Markdown tree itself.

**Testing**: `pytest` (427 tests green on this branch before any change). New tests live beside
their siblings in `tests/`, following the existing one-file-per-feature-area convention
(`test_weblinks.py`, `test_own_repo_web_strictness.py`, `test_links.py`).

**Target Platform**: any OS with Python; consumed as a CLI (`uvx`/`pipx`), a **pre-commit hook**
and a **GitHub Action**. This is why a JavaScript runtime is not an option (research R1).

**Project Type**: single-project CLI library.

**Performance Goals**: no measurable regression when the feature is **off** — the added work must
be skipped entirely, not computed and discarded. When **on**, recognition is linear in the size of
the mermaid regions only, which are a small fraction of a tree.

**Constraints**:
- **No network added.** The single sanctioned network path (`web-check --online`) is untouched;
  this feature only changes *which links reach it*.
- **Byte-identical behaviour when disabled** (SC-018) — this is what makes the feature safe to ship
  into fail-closed gates.
- **Never writes inside a fenced region** (FR-060/SC-023), including the axis that *can* write.

**Scale/Scope**: measured across 26 repositories — 182 mermaid regions in 120 files, carrying 2,165
destinations. The largest single repository contributes 1,961 of them, all third-party, and does
not have the web axis enabled.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1 — see below.*

| Principle | Verdict | Why |
|---|---|---|
| **I. Single responsibility — links & uuids only** | ✅ | Narrows *where* an existing axis looks. No new operation, no document semantics, no entity model. The two core operations remain exactly two |
| **II. Safe by default — dry-run first** | ✅ | Off by default; opt-in per repository; report-only items that cannot be written even in the writing mode |
| **III. Plain, self-contained, tool-agnostic** | ✅ | No format change. Nothing is written into a diagram, so a repository with diagrams stays exactly as usable without the tool as it is today |
| **IV. Deterministic — no heuristics, no AI** | ✅ | Pure textual recognition over a region produced by the existing pure function. No new network path; the `--online` carve-out is unchanged |
| **V. Test-first & acceptance-driven** | ⏳ **binding** | Every edge case in the spec is a failing test **before** implementation, and SC-019 additionally requires **seeding a defect and observing it caught** — a clean tree staying clean proves nothing |
| **Technical Constraints** | ✅ | **Zero new dependencies.** Distribution unchanged: still one `uvx` command, still a pre-commit hook, still an Action |

**Post-Phase-1 re-check**: ✅ unchanged. Phase 1 surfaced one new constraint (R4: destinations
inside diagrams are not anchorable) and it **tightens** Principles II and III rather than
straining them. No entry is needed in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/017-mermaid-web-links/
├── spec.md              # what and why
├── plan.md              # this file
├── research.md          # Phase 0 — the six decisions, with the measurements behind them
├── data-model.md        # Phase 1 — the two concepts and their rules
├── quickstart.md        # Phase 1 — how to prove it works, including the seeded defect
├── contracts/
│   └── cli.md           # Phase 1 — the user-visible surface (flag, config key, output, exit codes)
├── checklists/
│   └── requirements.md  # spec quality checklist
└── tasks.md             # Phase 2 — created by /speckit-tasks, NOT by this command
```

### Source Code (repository root)

```text
src/darnlink/
├── links.py         # region computation lives here — REUSED, and the recogniser joins it
├── weblinks.py      # the read axis: finds web links, classifies, anchors. Gains the union
├── cli.py           # flag plumbing + the offline listing path (the second read caller)
├── repair.py        # UNCHANGED — write axis, FR-015 stands
└── robustify.py     # UNCHANGED — write axis, FR-015 stands

tests/
├── test_mermaid_web_links.py   # new: the recogniser and every edge case in the spec
├── test_weblinks.py            # extended: the union, and report-only under the writing mode
└── test_links.py               # extended: mermaid regions are a subset of code regions
```

**Structure Decision**: single project, existing layout, no new package. The recogniser belongs
next to the region computation it depends on (`links.py`), not in a module of its own: it is a few
dozen lines that only make sense against a region, and a separate module would invite a second
notion of what a region is — the exact failure FR-054 forbids.

**Two callers, not one.** The read axis has *two* entry points (the online web check and the
offline listing). Wiring only the first would produce a tool that reports a broken destination when
online and denies its existence when offline. Both are in scope; the tests cover both.

## Complexity Tracking

> No Constitution Check violations. Nothing to justify.

The one thing worth recording as *deliberately not done*: this feature does **not** make the write
operations see inside diagrams. That would amend FR-015 and reopen a decision feature 002 settled
with tests. If a future need arises, it is a new feature with its own spec — not a widening of this
one.
