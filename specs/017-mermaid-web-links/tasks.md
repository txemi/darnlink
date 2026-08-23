---

description: "Tasks for 017-mermaid-web-links"
---

# Tasks: see web links inside `mermaid` diagrams (read axis only, opt-in)

**Input**: design documents from `specs/017-mermaid-web-links/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli.md`,
`quickstart.md`

**Tests**: **mandatory and binding.** The constitution's Principle V is test-first, and SC-019 goes
further: a clean tree stays clean whether the check works or is blind, so *seeding a defect and
observing it caught* is the only evidence that counts. Every test task below precedes its
implementation task, and that ordering is the deliverable, not a preference.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency between them)
- **[Story]**: the user story from `spec.md` this serves

---

## Phase A — Fixtures (blocking; everything else builds on these)

- **T001** [P] Build the fixture tree helper described in `quickstart.md` §Setup, in
  `tests/test_mermaid_web_links.py`: a diagram with a **live** destination (the control), a
  **broken** one (the seeded defect), a comment line carrying the directive word, and a callback
  binding. Follow the existing fixture style in `tests/test_weblinks.py` — the web tests inject a
  fetcher instead of touching the network, and this feature must not be the one that breaks that.
- **T002** [P] Add the boundary fixtures: prose beginning with the directive word (outside any
  fence), a `mermaid` fence nested inside a longer fence, an unclosed `mermaid` fence, and a
  tilde-delimited `mermaid` fence.

---

## Phase B — Failing tests (US1: a diagram's links stop dying in silence)

> **These must fail before any `src/` change.** A test that passes now is testing nothing.

- **T003** [US1] Region filter: a fence whose info string names `mermaid` is recognised as a
  mermaid region; one that does not, is not. Assert the set of mermaid regions is a **subset** of
  the code regions returned by the existing computation — the invariant in `data-model.md` §1.
- **T004** [US1] Recogniser, happy path: the three measured shapes each yield their destination
  (`click <id> "<dest>" …`, `click <id> href "<dest>" …`, and with a trailing target). FR-055.
- **T005** [US1] End-to-end, **flag on**: the broken destination in the fixture is reported; the
  control is reported as ok. This is SC-019 — the seeded defect.
- **T006** [US1] End-to-end, **flag off**: the same run reports neither. Same fixture, same
  command, opposite expectation. If T005 and T006 ever agree, the feature is not wired.
- **T007** [US1] Both entry points report the **same** destinations for the same tree: the online
  check and the offline listing must not disagree about what exists. Per `plan.md`, a tool that
  reports a broken destination online and denies it offline is worse than no tool.

---

## Phase C — Failing tests (US2: enabling it does not set the fleet on fire)

- **T008** [US2] Disabled is byte-identical: full output **and** exit code unchanged against the
  pre-change behaviour, on a tree that contains mermaid links. SC-018.
- **T009** [US2] A repository with no mermaid regions is unaffected whether the flag is on or off.
  FR-059.
- **T010** [US2] No network is attempted for a diagram destination when the flag is off — asserted
  through the injected fetcher, which must record zero calls attributable to it. SC-022.

---

## Phase D — Failing tests (US3: precision, and the write protection)

- **T011** [US3] A comment line (`%%`) containing a full directive yields **nothing**. FR-056.
  This case is real, not hypothetical: one exists in a measured tree.
- **T012** [US3] A directive that binds a callback rather than a destination yields **nothing**.
  FR-057.
- **T013** [US3] Prose beginning with the directive word, outside any fence, yields nothing; and a
  `mermaid` fence nested inside a longer fence is never scanned.
- **T014** [US3] Unclosed fence: the region runs to end of file and a directive after the opener is
  recognised. This is **inherited** from FR-016 — the test exists to prove the region computation
  was reused, not re-implemented (FR-054). Tilde fences behave identically.
- **T015** [US3] **Report-only, happy path**: the read axis in its **writing** mode, over a tree
  whose only candidates are inside a diagram, writes **nothing** — byte-diff of the tree. SC-023.
- **T016** [US3] **Report-only, mixed file**: a file with both a prose web link and a diagram
  destination — the prose link is anchored, the diagram bytes are unchanged.
- **T017** [US3] **⚠️ Report-only, adversarial**: take a report-only item and invoke the
  edit-producing path **directly**, bypassing the normal call site. The file must still be
  untouched. *Rationale: if the protection lives only in the caller, it disappears the day someone
  adds a second caller — which is exactly how this feature came to exist.*
- **T018** [US3] **The property survives the report**: the offline listing currently projects each
  link to `{file, href, anchored}`, dropping everything else. Assert the JSON distinguishes a
  destination that **can never** be anchored from one that merely **is not yet** — otherwise a
  consumer reconstructs an item without the property, which is the same defect one layer out.
- **T019** [US3] The write operations (repair, robustify) are unchanged with the flag both on and
  off: byte-diff of every fenced region across all four combinations. FR-053 — the check that says
  out loud that FR-015 is not amended.

---

## Phase E — Implementation (only after B–D are red)

- **T020** [US1] `src/darnlink/links.py`: derive mermaid regions from the existing fenced-region
  computation by filtering on the info string. **Do not** add a second notion of a fenced block.
- **T021** [US1] `src/darnlink/links.py`: the recogniser — a pure textual function over a region
  body, skipping comment lines and destination-less directives, producing items in the shape the
  web axis already consumes. No network, no fuzziness (FR-058).
- **T022** [US1] `src/darnlink/weblinks.py`: union the recognised destinations into the online
  check, gated by the opt-in. Recall from `research.md` R3 that lifting the exclusion alone finds
  nothing — the existing finder looks for Markdown link syntax, which a directive is not.
- **T023** [US1] `src/darnlink/cli.py`: the same union in the **offline listing** path, and carry
  the report-only property into its JSON projection (T018).
- **T024** [US3] Enforce report-only **where the edit is produced**, not where it is requested —
  a property of the item, per `data-model.md` §2. T017 is the test that this was done in the right
  place.
- **T025** [US2] Flag plumbing on the read axis only. **Not** on the core command: offering it
  there would imply the write axis can honour it.

---

## Phase F — Rollout surface

- **T026** [P] `recipes/`: the configuration key, absent-means-off, mapping to the flag. Extend
  `tests/test_recipe_gate.py` / `test_recipe_examples.py` in the existing style.
- **T027** [P] `README.md` + `CHANGELOG.md`: what the switch does, and — stated plainly — that
  destinations inside diagrams are watched but **never rewritten**, so a permanently un-anchored
  destination is a normal state and not a defect.

---

## Phase G — Acceptance

- **T028** Run the seven `quickstart.md` scenarios end to end against a **disposable** tree, never
  a live one (constitution, Development Workflow).
- **T029** Full suite green (427 tests were green on this branch before any change; the count must
  only go up), and every test from B–D now passing **for the right reason** — re-break the fixture
  and watch T005 fail again. A test that passes because the fixture stopped being broken is a false
  pass.

---

## Dependencies

```
A (T001-T002)  →  B, C, D  →  E  →  F  →  G
```

- Phase A blocks everything: the fixtures are the measurement instrument.
- **B, C and D must be RED before any task in E begins.** This is the binding constraint.
- Within E, T020 blocks T021, which blocks T022 and T023. T024 is independent of the union work and
  can proceed once T021 exists.
- F depends on E. G depends on everything.

## Parallelisable

`[P]` on T001/T002 (distinct fixtures), and on T026/T027 (recipes and docs touch different files).
Everything in E touches overlapping modules and is deliberately **not** marked parallel.

## Out of scope — recorded so it is not re-litigated

- Making the **write** operations see inside diagrams. That amends FR-015 and reopens a decision
  feature 002 settled with tests. A future need is a new feature with its own spec.
- Markdown-style links inside diagram labels, and relative destinations inside diagrams: **zero**
  occurrences across 26 measured repositories. Scope widens on evidence, not on speculation.
