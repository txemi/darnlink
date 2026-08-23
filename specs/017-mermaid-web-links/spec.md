# Feature Specification: see web links inside `mermaid` diagrams (read axis only, opt-in)

**Feature Branch**: `017-mermaid-web-links`

**Created**: 2026-08-23

**Status**: Draft

**Input**: A diagram's `click` directives carry destinations — most of them URLs into the author's
own repository. They live inside a ```` ```mermaid ```` fence, so feature 002 hides them from every
axis, including the read-only ones. The result is a class of link that **no gate has ever watched**:
it dies the moment a file moves, silently, while the tree stays green. This feature lets the
**read** axes see those links. It does **not** touch repair or robustify, so FR-015 stands
unchanged.

---

## The gap, precisely

Feature 002 (FR-015) is a **write-side** rule, and says so:

> MUST ignore any link ... for BOTH operations (**repair and robustify**).

Both are mutations. Its stated failure mode — *"ignore too much (skip a real link), never rewrite
code"* — is about not corrupting an example. **Reporting a link is not rewriting it.** But
`code_spans()` is consumed by four callers, and two of them are read-only:

| Caller | Axis | Should mermaid be visible? |
|---|---|---|
| `repair.py` | write | **No** — FR-015 stands |
| `robustify.py` | write | **No** — FR-015 stands |
| `weblinks.py` (`web-check`) | read | **Yes**, opt-in |
| `cli.py` (offline web listing) | read | **Yes**, opt-in |

A mermaid `click` destination is **not a code example**. It is a navigational link that happens to
be written in a diagram's syntax — the exact thing 002 exists to protect elsewhere, and the exact
thing nothing protects here.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A diagram's links stop dying in silence (Priority: P1)

A maintainer keeps an architecture diagram whose nodes are clickable: each `click` points at a file
in the same repository, written as a full URL. The files are later reorganised into subfolders. The
maintainer wants the run to report those destinations as broken instead of staying green.

**Why this priority**: This is the whole feature. Without it the diagram is a blind spot: measured
on a real tree, a single folder reorganisation killed **14 of a diagram's `click` destinations at
once**, and every gate stayed green. The links had to be found by hand.

**Independent Test**: A file with a ```` ```mermaid ```` fence containing
`click A href "https://github.com/<owner>/<repo>/blob/main/moved.md"` where `moved.md` no longer
exists at that path; run the read axis with the feature enabled; assert the destination is
reported. Run it with the feature disabled; assert nothing is reported and the output is identical
to today's.

**Acceptance Scenarios**:

1. **Given** a `mermaid` fence with a `click` whose destination is a live URL, **When** the read
   axis runs with the feature enabled, **Then** the destination appears in the report exactly as a
   prose web link would.
2. **Given** the same file, **When** the read axis runs with the feature **disabled** (the
   default), **Then** the destination is not reported and the run is byte-identical to a run on the
   current release.
3. **Given** the same file, **When** `--write` runs (repair/robustify) with the feature enabled,
   **Then** the bytes inside the fence are unchanged.

---

### User Story 2 - Enabling it does not set the fleet on fire (Priority: P1)

An operator runs the same tool across many repositories with fail-closed gates. Turning on a check
that suddenly sees thousands of new destinations — most of them third-party services that can never
be fixed from here — would block every push at once.

**Why this priority**: Equal to P1 above, because a correct feature that cannot be switched on
safely does not get switched on. Measured across a real fleet: the same change would expose **33**
own-repository destinations in one repo (all currently valid) and **2,108** third-party
destinations in two others.

**Independent Test**: With no configuration change, every existing repository behaves exactly as
before — verified by running the full read axis on a tree containing mermaid links and diffing the
output against the current release.

**Acceptance Scenarios**:

1. **Given** a repository that does not opt in, **When** any command runs, **Then** mermaid
   destinations are invisible, as today.
2. **Given** a repository that opts in, **When** the read axis runs, **Then** only that
   repository's behaviour changes.

---

### User Story 3 - The diagram's own comments are not mistaken for links (Priority: P2)

Diagram authors annotate their diagrams with comments, and those comments discuss the very
directives around them.

**Why this priority**: Lower than P1 because it degrades precision rather than blocking the
feature — but it is not hypothetical: a real tree contains a mermaid comment line whose prose
includes the word `click`. A recogniser that ignores comments produces false findings, and a gate
that cries wolf gets switched off.

**Independent Test**: A fence containing `%% click A "https://example.com/gone"`; assert nothing is
reported.

**Acceptance Scenarios**:

1. **Given** a mermaid comment line that contains a `click` directive, **When** the read axis runs
   with the feature enabled, **Then** it is not reported.
2. **Given** a `click` directive that binds a callback rather than a destination, **When** the read
   axis runs, **Then** it is not reported — it carries no destination.

---

### Edge Cases

- **A fence that is never closed**: inherited unchanged from FR-016 — the region runs to end of
  file. Nothing new is needed and nothing new is claimed.
- **A `mermaid` fence shown as an example inside a longer fence**: the outer fence wins, because
  region detection is the existing one. The inner text is never scanned.
- **Prose that begins with the word "click"**: cannot be reached — recognition happens only inside
  a mermaid region. Measured: two such lines exist in a real tree, both in ordinary prose.
- **A destination that is a relative path rather than a URL**: out of scope (see Assumptions).
  It is not reported by either axis, exactly as today.
- **Tilde fences** (`~~~mermaid`): treated identically to backtick fences, per FR-016.
- **An info string with extra words** (```` ```mermaid ````+ attributes): recognised as mermaid.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-052**: The read axes (`web-check`, online and offline) MUST be able to see web links whose
  start position falls inside a fenced region whose info string names `mermaid`. This is
  **opt-in and off by default**: with no configuration, behaviour is unchanged.
- **FR-053**: The write operations (repair, robustify) MUST continue to ignore every link inside
  any fenced region, mermaid included, whether or not the feature is enabled. **FR-015 is not
  amended by this feature.**
- **FR-054**: Region detection MUST reuse the existing fenced-region computation (FR-016). This
  feature MUST NOT introduce a second, parallel notion of what a fenced block is.
- **FR-055**: Inside a mermaid region, a destination MUST be recognised from a `click` directive
  that carries a quoted destination, in the forms `click <id> "<dest>" [...]` and
  `click <id> href "<dest>" [...]`, where a trailing target or tooltip does not affect
  recognition.
- **FR-056**: A mermaid comment line (one whose first non-blank characters are `%%`) MUST NOT
  yield a destination, even when it contains the text of a `click` directive.
- **FR-057**: A `click` directive that binds a callback rather than a destination MUST NOT yield a
  destination.
- **FR-058** (determinism): Recognition MUST be a pure textual function — no network, no
  heuristics, no fuzzy matching — and MUST compose with `--ignore-block` markers and with the
  existing ignore mechanisms, exactly as FR-018 requires of region detection.
- **FR-059**: Enabling the feature MUST NOT change the exit code or output of any repository that
  contains no mermaid regions.

### Key Entities

- **Mermaid region**: a fenced region (FR-016) whose info string names `mermaid`. It is a
  *subset* of the existing code regions, never a new kind of region.
- **Mermaid destination**: a destination recognised from a `click` directive inside a mermaid
  region. Once recognised, it is an ordinary web link and is handled by the existing web axis with
  no special case.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-018**: With the feature disabled, output on any tree is **identical** to the current
  release — provable by diffing full runs before and after, on a tree that contains mermaid links.
- **SC-019**: With the feature enabled, a destination inside a mermaid diagram that points at a
  path which no longer exists is reported; the same run before the change reports nothing. Proven
  by **seeding a defect and observing it caught** — not merely by observing a clean tree stay
  clean.
- **SC-020**: Bytes inside any fenced region are unchanged by a `--write` run whether the feature
  is on or off (byte-diff of the fenced regions).
- **SC-021**: Comments and callback bindings inside a diagram produce **zero** findings.
- **SC-022**: A repository that does not opt in shows no change in behaviour, exit code, or
  network traffic.

---

## Assumptions

- **Only the read axes are in scope.** Making the write operations see inside a diagram is
  deliberately excluded: it would amend FR-015 and reopen a decision that feature 002 settled.
- **Only `click` destinations are in scope.** Markdown-style links written inside a diagram's
  labels are excluded: measured across a real fleet of 26 repositories, they do **not occur** —
  every one of 2,165 destinations came from a `click` directive. If they appear later, the scope
  can be widened on evidence.
- **Only absolute destinations are in scope.** Relative paths inside a diagram do not occur in the
  measured trees (zero of 2,165). Resolving them would pull the core's path resolution into a
  region it has never entered, for no observed benefit.
- **The destination grammar is a regular, line-oriented one.** Measured over 2,165 real
  directives, three shapes account for all of them, each on a single line with the destination in
  double quotes. No nesting, no recursion.
- **Off by default is a requirement, not a preference.** The tool is consumed by fail-closed gates
  across many repositories; a check that switches itself on everywhere is how every push breaks at
  once.

---

## Constitution Check

- **I. Single responsibility** — ✅ still links + uuid only. This narrows *where* an existing axis
  looks; it adds no document semantics and no new operation.
- **II. Safe by default** — ✅ off by default, opt-in, read-only. It cannot write anything the
  current release would not write.
- **III. Plain, tool-agnostic** — ✅ no format change; a repository stays fully usable without the
  tool, and diagrams stay plain Markdown.
- **IV. Deterministic, no AI** — ✅ pure textual recognition over a region computed by the existing
  pure function. The network stays confined to the existing sanctioned `web-check --online`
  carve-out; this feature adds no new network path.
- **V. Test-first** — ⏳ required: the edge cases above (comment lines, callback bindings, unclosed
  fence, nested example fence, prose beginning with the directive word) are written as failing
  tests **before** implementation, and SC-019 additionally requires seeding a defect and observing
  it caught.

**Technical Constraints** — ✅ **no new dependency.** Region detection is reused; recognition is a
pure textual function in the same style as the existing inline-region detection (FR-017). Adding a
grammar engine or a Markdown library was evaluated and rejected: the measured grammar is regular
and one-line, so a grammar engine buys nothing, and either dependency would breach
*standard library + `python-frontmatter` only*. A JavaScript parser was rejected outright — it
would also breach *Distribution* (`uvx`/`pipx`, pre-commit hook, GitHub Action), and the machine
where this was measured has no JavaScript runtime installed at all.

No violations; no complexity-tracking entries.
