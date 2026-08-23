# Phase 0 — Research: web links inside `mermaid` diagrams

All unknowns in the Technical Context are resolved below. No `NEEDS CLARIFICATION` remains.

---

## R1. How to recognise the destination — grammar engine, Markdown library, or a textual function?

**Decision**: a **pure textual function**, in the same style as the existing inline-region
detection (FR-017). **No new dependency.**

**Rationale**: the destination grammar was measured, not guessed. Across a fleet of 26
repositories, **2,165** `click` directives occur, and they reduce to **three shapes**:

```
1961  click <id> href "<dest>" _blank
 147  click <id> "<dest>" _blank
  57  click <id> href "<dest>"
```

Every one is a **single line** with the destination in double quotes. There is no nesting and no
recursion: the language is **regular**. A grammar engine earns its keep on recursive structure,
and there is none here — it would buy a permanent maintenance obligation (a grammar to chase when
the diagram syntax moves) in exchange for nothing measurable.

**Alternatives considered**:

| Alternative | Measured | Rejected because |
|---|---|---|
| `lark` (grammar engine) | 110 KB wheel, pure Python, **zero runtime dependencies** — genuinely light | Breaches *Technical Constraints* (`standard library + python-frontmatter only`), which in this project means a **constitution amendment** and a re-check of every live spec. And it solves recursion the measurement says does not exist |
| The upstream diagram parser | ships as a JavaScript package with its own dependency | Breaches *Technical Constraints* **and** *Distribution* (`uvx`/`pipx`, pre-commit hook, GitHub Action). The machine this was measured on has **no JavaScript runtime installed at all**: requiring one would break the gates where they actually run |
| A Markdown library, to replace region detection | 90 KB, but pulls a second package (1 → 3 total) | Region detection is **not the broken part**: it is specified (FR-016), covered by tests, and no defect has been reported against it. Replacing the healthy component to reach the sick one adds risk without removing any |

**On the instruction that prompted this feature** — *"use libraries to read the diagram, do not use
string parsing, which causes problems"*: the part of string parsing that causes problems is the
**region slicing** — nested fences, unclosed fences, tilde versus backtick, info strings. This
design does not re-implement it; it **reuses** the existing, specified, tested computation (R2).
What remains is a fixed one-line directive with a quoted destination inside an already-bounded
region. Recognising the project's own link grammar by textual pattern is what the codebase already
does throughout, and FR-018 **requires** region detection to be "a pure textual function (no
network, no heuristics)". Using a grammar engine here while the core link is recognised textually
would be inconsistent with the project itself.

---

## R2. Where does the region come from?

**Decision**: reuse the existing fenced-region computation (FR-016) and **filter** it by info
string. A mermaid region is a *subset* of existing code regions, never a new kind of region.

**Rationale**: everything hard about the boundary is already solved and paid for — unclosed fence
runs to EOF, closing fence of equal-or-greater length, indent up to 3, tildes and backticks do not
close each other, an example fence nested in a longer fence is not scanned. Filtering by info
string inherits all of it for free and keeps a single source of truth. A second, parallel notion of
"what is a fenced block" is the failure mode this decision exists to prevent (FR-054).

**Alternatives considered**: computing mermaid regions independently — rejected: two computations
that must agree forever, and the moment they disagree the write axis and the read axis disagree
about what code is.

---

## R3. The recognised destination is not a Markdown link — how does it reach the web axis?

**Decision**: the mermaid recogniser yields items in the **same shape** the web axis already
consumes, and the axis handles them with **no special case** downstream.

**Rationale**: the existing web-link finder scans for Markdown link syntax. A diagram's `click`
directive is not Markdown link syntax, so lifting the region exclusion **alone** would find
nothing — the recogniser has to produce the item. Producing it in the existing shape means
classification, reporting, exit codes and the own-repository strictness rule (feature 016) all
apply unchanged, which is the whole point: once recognised, it is an ordinary web link.

**Alternatives considered**: a parallel reporting path for diagram links — rejected: it would
duplicate classification and drift from the main axis, and feature 016's rules would have to be
re-implemented.

---

## R4. ⚠️ Can a diagram destination be anchored? — **No, and this constrains the design**

**Decision**: destinations recognised inside a diagram are **report-only**. They are never
rewritten and never anchored (FR-060).

**Rationale — and this is a constraint discovered during research, not an assumption**: the web
axis is not purely read-only. In its writing mode it **anchors** a link by appending an HTML
comment after it. Inside a diagram, an HTML comment is **not a comment**: diagrams have their own
comment syntax (`%%`), so an appended HTML comment becomes diagram content and **corrupts the
diagram**. There is also nowhere to put it: a `click` directive has no `[text](href)` form to
append to.

This is the same danger feature 002 protects the write operations from, arriving through the one
axis 002 does not cover. Left unstated, this feature would have made the tool write into diagrams —
the exact opposite of its own premise.

**Consequence**: `report-only` is a **property of the item**, enforced where the edit is produced,
not a flag the caller may forget to pass. SC-023 verifies it by byte-diffing the tree after a
writing run.

**Alternatives considered**: emitting a `%%`-style anchor that the diagram would tolerate —
rejected. It invents a second anchor format for one diagram dialect, breaks *Plain, Self-Contained,
Tool-Agnostic* (a repository must stay usable without the tool), and buys nothing: the value here
is **noticing** that a destination died, not repairing it in place.

---

## R5. How is the opt-in expressed, and why off by default?

**Decision**: off by default; enabled per repository through the existing configuration surface,
alongside the other axis switches.

**Rationale**: measured, the same change exposes **33** own-repository destinations in one
repository — all currently valid, so it goes green on day one — and **2,108** third-party
destinations in two others, which can never be fixed from those repositories and would only add
traffic and noise. The tool is consumed by **fail-closed gates**: a check that switches itself on
everywhere is how every push in a fleet breaks at once. Off by default also makes SC-018
(byte-identical output with the feature disabled) a testable claim rather than a hope.

**Alternatives considered**: on by default with an opt-out — rejected on the measurement above.
Auto-enabling where diagrams are detected — rejected: "it turned itself on" is indistinguishable
from a regression when a gate goes red.

---

## R6. What does *not* need research, because it was measured to be absent

- **Markdown-style links inside diagram labels**: **zero** occurrences of 2,165. Out of scope.
- **Relative destinations inside diagrams**: **zero** occurrences. Out of scope — resolving them
  would drag core path resolution into a region it has never entered, for no observed benefit.
- **Prose beginning with the directive word**: two occurrences in a real tree, both outside any
  diagram region. Unreachable by construction, since recognition happens only inside a region.
- **Diagram comment lines containing the directive word**: **one real occurrence**. Reachable, so
  it is a requirement (FR-056) and a test, not an assumption.
