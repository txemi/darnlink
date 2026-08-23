# Specification Quality Checklist: see web links inside `mermaid` diagrams (read axis only, opt-in)

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-23
**Feature**: `spec.md`, one level up. Deliberately not a Markdown link: no spec in this
repository carries frontmatter, so a link here would make the gate want to invent a `uuid` for one.

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

Two items were tightened during validation rather than passed as written:

1. **"No implementation details"** — the first draft named the specific source files and the
   function that computes fenced regions. File and function names are *how*, not *what*. They were
   replaced by the capability ("the existing fenced-region computation, FR-016") in the
   requirements. The one place where a concrete map survives is *The gap, precisely*, which is
   background rather than a requirement — it is what makes the read/write split legible, and
   feature 002's own spec sets that precedent.

2. **"Success criteria are measurable"** — SC-019 originally read "dangling destinations inside
   diagrams are reported". That is not measurable on a healthy tree: a tree with nothing broken
   produces zero findings whether the check works or is blind. It was rewritten to require
   **seeding a defect and observing it caught**, which is the only form that distinguishes *dry*
   from *blind*.

Numbering continues the repository-wide sequences rather than restarting: FR-052..FR-059 and
SC-018..SC-022 (previous maxima FR-051 and SC-017).
