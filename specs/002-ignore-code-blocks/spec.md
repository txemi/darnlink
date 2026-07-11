# Feature Specification: ignore links inside code (fenced & inline)

**Feature Branch**: `002-ignore-code-blocks`

**Created**: 2026-06-08

**Status**: Draft

**Input**: darnlink must never touch a Markdown link that lives inside a code span or a fenced
code block. Those are *examples of code*, not navigational prose links: rewriting them corrupts
documentation. This refines the scope of both operations (repair & robustify); it does not add a
new capability, so it does not amend Constitution Principle I.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Robustify must not mangle code examples (Priority: P1)

A doc author keeps Markdown snippets inside fenced code blocks (```` ``` ````/`~~~`) or inline
code (`` ` ``) that contain example links such as `[text](path.md)`. Running darnlink robustify
must leave every link inside code untouched, while still robustifying the real prose links around
it.

**Why this priority**: This is the most common corruption in real repos (READMEs, playbooks,
the darnlink docs themselves show robust-link examples in fences). Without it, `--robustify`
is unsafe to run on any documentation-heavy tree.

**Independent Test**: A file with one prose link and one identical link inside a ```` ```markdown ````
fence; run `darnlink --robustify --write`; assert only the prose link gained a `<!-- uuid: … -->`
and the fenced bytes are byte-for-byte unchanged.

**Acceptance Scenarios**:

1. **Given** `A.md` has a prose link `[B](B.md)` and, inside a fenced block, `[B](B.md)`,
   **When** `darnlink --robustify --write` runs, **Then** only the prose link is upgraded; the
   text inside the fence is unchanged.
2. **Given** an inline code span `` `[x](y.md)` `` on a line, **When** robustify runs, **Then**
   the link inside the backticks is not touched.
3. **Given** a fenced block that is never closed (runs to EOF), **When** darnlink runs, **Then**
   all links from the opening fence to EOF are treated as code and left untouched (safe
   over-ignore: never corrupt, even at the cost of skipping a real link).

---

### User Story 2 - Repair must not rewrite robust-link examples in docs (Priority: P2)

A spec/README shows a *complete* robust link (`[text](path.md) <!-- uuid: … -->`) inside a fence
as documentation. Repair must not rewrite that example's path even if a file with that UUID exists
elsewhere.

**Acceptance Scenarios**:

1. **Given** a fenced block containing `[t](old.md) <!-- uuid: U -->` and a real file with
   `uuid: U` at a different path, **When** `darnlink --write` runs, **Then** the fenced example is
   left untouched.

---

### Edge Cases

- **Fenced code**: opened by a line of 3+ backticks or 3+ tildes (indented ≤ 3 spaces), closed by
  a line of the same fence character of equal-or-greater length. An info string after the opener
  (```` ```markdown ````) is allowed. Tildes and backticks do not close each other.
- **Inline code**: a run of N backticks is closed by the next run of exactly N backticks; the span
  between (inclusive) is code. An unterminated opening run is not a code span.
- **Nesting**: inline-code detection does not run inside fenced regions (the fence already covers
  them).
- **Interaction with `--ignore-block`**: code spans are ignored *in addition to* the existing
  generated-block markers; both mechanisms compose.
- **Unclosed fence**: ignore from the opener to EOF (over-ignoring is safe; corrupting is not).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-015**: MUST ignore any link (plain or robust) whose start position falls inside a fenced
  code block or an inline code span, for BOTH operations (repair and robustify). This is the
  default behavior, not opt-in.
- **FR-016**: Fenced-block detection MUST support both ```` ``` ```` and `~~~` fences, an optional
  info string, indentation up to 3 spaces, and a closing fence of equal-or-greater length of the
  same character; an unclosed fence extends to EOF.
- **FR-017**: Inline-code detection MUST pair a run of N backticks with the next run of exactly N
  backticks; an unterminated run is not code.
- **FR-018** (determinism): code-span detection MUST be a pure textual function (no network, no
  heuristics) and compose with `--ignore-block` markers.

## Success Criteria *(mandatory)*

- **SC-006**: For any file, links inside fenced or inline code are never modified by repair or
  robustify (provable by byte-diff of the code regions before/after `--write`).
- **SC-007**: Real prose links outside code are still robustified/repaired in the same pass
  (the feature narrows scope, it does not disable the operations).
- **SC-008**: Idempotent and deterministic as before (Constitution IV, FR-008 unaffected).

## Assumptions

- CommonMark-ish fences are sufficient; exotic constructs (e.g. fences inside list items at deep
  indentation) fall back to the safe over-ignore behavior rather than precise parsing.
- The safe failure mode is to ignore *too much* (skip a real link), never to rewrite code.

## Constitution Check

- **I. Single responsibility** — ✅ still links + uuid only; this narrows what counts as a link.
- **II. Safe by default** — ✅ strengthens safety; default behavior, no new flag, fail-safe = skip.
- **III. Plain, tool-agnostic** — ✅ no format change; robust-link grammar unchanged.
- **IV. Deterministic, no AI** — ✅ pure textual span computation.
- **V. Test-first** — ✅ failing tests for fenced + inline written before the implementation.

No violations; no complexity-tracking entries.
