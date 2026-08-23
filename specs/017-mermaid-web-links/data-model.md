# Phase 1 — Data model

This feature introduces **no persisted data** and no new user-facing entity. It adds two concepts
that live for the duration of a single scan.

---

## 1. Mermaid region

**What it is**: a fenced region whose info string names `mermaid`.

**Where it comes from**: the existing fenced-region computation (FR-016), filtered by info string.
It is **derived, never computed independently** (FR-054).

| Rule | Source |
|---|---|
| Opened by 3+ backticks or 3+ tildes, indented at most 3 | inherited, FR-016 |
| Closed by the same fence character, length ≥ the opener | inherited, FR-016 |
| An unclosed fence extends to end of file | inherited, FR-016 |
| Backticks and tildes do not close each other | inherited, FR-016 |
| A fence nested inside a longer fence is never scanned | inherited, FR-016 |
| Its info string, lowercased, names `mermaid` | **new, this feature** |

**Invariant**: every mermaid region is also a code region. The set of mermaid regions is a
**subset** of what the write axis ignores — so nothing this feature recognises can ever be
something the write axis was allowed to touch.

**Where the info string ends**: the first line break after the opening fence. Everything after
that line and before the closing fence is the region's body; only the body is scanned.

---

## 2. Mermaid destination

**What it is**: a destination recognised from a `click` directive inside a mermaid region's body.

**Shape**: identical to an ordinary web link, so that classification, reporting, exit codes and
feature 016's own-repository strictness apply with **no special case** (research R3).

| Attribute | Value | Note |
|---|---|---|
| destination | the quoted string from the directive | the only field the directive really carries |
| position | absolute offset in the file | used for ordering and for reporting the location |
| display text | none | a directive has no link text; reporting must not assume one |
| existing anchor | never | a diagram cannot carry the anchor comment (R4) |
| **report-only** | **always true** | **enforced where edits are produced, not where they are requested** |

### Recognition rules

| Rule | Requirement |
|---|---|
| Recognised only inside a mermaid region body | FR-055 |
| `click <id> "<dest>" [trailing]` yields `<dest>` | FR-055 |
| `click <id> href "<dest>" [trailing]` yields `<dest>` | FR-055 |
| A trailing target or tooltip does not affect recognition | FR-055 |
| A line whose first non-blank characters are `%%` yields nothing | FR-056 |
| A directive binding a callback rather than a destination yields nothing | FR-057 |
| Recognition is pure and textual — no network, no fuzziness | FR-058 |

### The rule that is not a rule about recognition

**Report-only is a property of the item, not of the caller** (FR-060). Modelling it as a flag the
caller passes would mean any future caller can forget it, and the failure mode of forgetting is
*writing an HTML comment into a diagram* — silent corruption of the exact kind feature 002 exists
to prevent. It is enforced at the point where an edit would be produced, so a caller that does not
know about diagrams still cannot corrupt one.

---

## 3. Configuration

| Concept | Default | Scope |
|---|---|---|
| "see destinations inside diagrams" | **off** | per repository, alongside the other axis switches |

**No new storage.** It joins the existing configuration surface; nothing is written anywhere new.

**State transitions**: none. The setting is read once per invocation; there is no lifecycle, no
migration, and no persisted state to upgrade.
