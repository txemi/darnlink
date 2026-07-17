# Feature Specification: source-only opt-out via an in-file marker (`darnlink-ignore-links`)

**Feature Branch**: `006-ignore-links-marker`

**Created**: 2026-07-17

**Status**: Draft

**Input**: A Markdown file must be able to declare, **from within itself**, that darnlink should
never rewrite *its own* links — while still being a first-class **target** that others can anchor to.
The motivating case is the same one feature 003 was written for (a generator rewrites the file, so
any anchoring darnlink does is churn), but 003 cannot serve it: `<!-- darnlink-ignore-file -->`
removes the file from the graph **entirely**, including as a target. Generated indexes such as an
auto-built `INDEX.md` / `PRIORITIES.md` are exactly the files other documents link to *most*, and
those inbound links must stay robust. This feature splits the two axes that 003 fused, so a file can
opt out of being a **source** without giving up being a **target**.

## The two axes (and why 003 fused them)

darnlink asks two independent questions about every file:

| Axis | Question | Today |
|---|---|---|
| **Source** | Do I rewrite the links *inside* this file? | `ignore-file` (all) · `--ignore-block` (a region) |
| **Target** | May others anchor to this file by its `uuid`? | `ignore-file` (all) |

`ignore-file` answers **both** with "no" — it is a single switch on two axes. FR-019 says so
explicitly: an opted-out file "is neither scanned as a source … nor indexed as a target". For its
stated motivating case that is the wrong trade: a generated index wants **source: no** (or the
generator's next run overwrites the anchors) and **target: yes** (or every inbound link to it breaks
the moment it moves). There is no way to ask for that combination today.

## Evidence this gap is real (not hypothetical)

A consumer repository (`project_map`, ~1500 uuids) hit exactly this and **could not adopt the
marker**. Its generated files are heavily-linked targets, so `ignore-file` was not an option. It
worked around it with an **external allowlist** consumed by its own gate — a list of globs the gate
refuses to complain about (~675 exempt findings). The workaround is strictly worse than a marker:

- **It cannot prevent, only detect.** darnlink does not know the allowlist exists, so
  `darnlink --robustify --write` still writes into those files. The gate only notices afterwards,
  and a human must restore them by hand. This misfired **three times** (2026-06-11, 07-16, 07-17) —
  the same accident, by different people, because the tool offers the write and the list only
  complains later.
- **It lives outside the files**, which is what the constitution's Principle III ("everything needed
  is in the files themselves") exists to avoid, and what 003's own rationale argued against.

## Why `ignore-links` and not `generated`

The obvious name for the motivating case is `darnlink-generated`. It is rejected: "generated" is a
claim about *what a document means*, and Principle I is explicit that darnlink "knows about Markdown
files, links, and a `uuid` frontmatter field — nothing else … Any feature that needs to understand
the *meaning* of a document is out of scope." `ignore-links` describes only the mechanism — *do not
touch the links in this file* — which is structural, checkable, and semantics-free. Being generated
is merely the most common *reason* a file asks for it; a hand-written file may ask for the same and
darnlink neither knows nor cares why.

This feature refines *which files participate, on which axis*. It adds no new capability and no
document semantics, so it does not amend Principle I.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-033**: A Markdown file containing the marker `<!-- darnlink-ignore-links -->` (outside any
  code span) MUST have the links **inside it** left untouched by every operation: they are never
  robustified and never repaired. This is default behavior for such a file, not opt-in.
- **FR-034**: The same file MUST remain indexed as a **target**: its frontmatter `uuid` resolves,
  inbound robust links pointing at it keep working, and they MUST still be repaired when the file
  moves. (This is the whole point of the feature, and the only difference from FR-019.)
- **FR-035**: Under `--robustify`, such a file MUST still be eligible to *receive* a `uuid` under the
  existing rules (reuse if present; creation still gated by `--create-frontmatter` and the
  `--no-create-frontmatter-for` deny-list). Opting out as a source says nothing about the target axis.
- **FR-036**: Marker detection MUST ignore occurrences inside fenced or inline code (composing with
  feature 002), so documentation showing the marker is unaffected.
- **FR-037**: Detection MUST be a pure textual check (deterministic, no network), tolerant of
  internal whitespace, matching the canonical keyword `darnlink-ignore-links`.
- **FR-038**: A link left plain (or left stale) because of this marker MUST be reported with a
  dedicated kind, in human and `--json` output — never skipped silently (Constitution II: no silent
  caps). It MUST NOT be reported as an actionable `robustify`/`repair` finding, so a strict gate
  (`--robustify` as a fail-closed check) passes on a tree whose generated files carry the marker.
- **FR-039**: If a file carries **both** markers, `darnlink-ignore-file` wins and the file is removed
  from the graph entirely (FR-019). The stronger claim takes precedence; the combination is not an
  error.
- **FR-040**: The marker MUST NOT be placed **before** the frontmatter block. The canonical reader
  (FR-023) only recognises a *leading* frontmatter block, so a marker on line 1 pushes `---` off the
  top and the file's `uuid` becomes unreadable — silently costing it the target axis, which is the
  entire point of this feature. Placement is therefore part of the contract: **frontmatter first,
  marker after it**. (003 is unaffected by this: an `ignore-file` file is dropped from the graph
  anyway, which is why its examples can lead with the marker.) Detection itself stays position-free
  (FR-037) — only the *interaction with frontmatter* imposes this ordering, and it is a property of
  the frontmatter format, not of the marker.

### Key Entities

- **Ignore-links marker**: an HTML comment `<!-- darnlink-ignore-links -->` that opts the file out of
  the **source** axis only. Invisible when rendered. Self-contained: no external list, no config.
  Contrast with the **ignore-file marker** (003), which opts out of both axes.

## Acceptance

1. **The motivating case.** A file `INDEX.md` carries the marker and holds a plain link to `B.md`
   (which has a `uuid`). `darnlink --robustify --write` leaves `INDEX.md` byte-identical, and the
   run reports the skip. A strict `darnlink --robustify` check exits 0.
2. **Still a target.** `A.md` holds a robust link to `INDEX.md` by uuid. `INDEX.md` moves.
   `darnlink --write` repairs `A.md` to the new path — the marker does not hide `INDEX.md` from the
   index. (This is what FR-019 makes impossible today.)
3. **Its own links are never repaired.** `INDEX.md` holds a robust link to `B.md`; `B.md` moves.
   `darnlink --write` leaves `INDEX.md` untouched and reports it. (The generator re-emits the correct
   path on its next run; darnlink must not fight it.)
4. **Documentation is safe.** A file showing `<!-- darnlink-ignore-links -->` inside a fenced code
   block does not opt itself out (composes with 002).
5. **Precedence.** A file with both markers behaves exactly as under FR-019.
