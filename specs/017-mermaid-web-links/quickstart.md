# Phase 1 — Quickstart: proving the feature works

The point of this guide is **not** to watch a clean tree stay clean. A blind check and a working
check produce identical output on a healthy tree — that is exactly how this class of link went
unwatched for so long. Every scenario below therefore starts by **breaking something on purpose**.

## Prerequisites

- The repository checked out on branch `017-mermaid-web-links`
- `uv` available (the project's runner)
- A scratch directory **outside** any real tree. Per the constitution: validate against a
  disposable clone, never a live tree

## Setup — the fixture tree

Create a scratch Markdown tree containing:

1. `moved.md` — an ordinary file with a `uuid` in its frontmatter, at a known path
2. `diagram.md` — a file containing a `mermaid` fence with **four** `click` directives:
   - one pointing at `moved.md` **where it currently is** (the control: must stay ok)
   - one pointing at a path that does **not** exist (the seeded defect)
   - one written as a diagram comment line (`%%` …) that contains the directive word
   - one that binds a callback instead of a destination
3. `prose.md` — a paragraph that **begins** with the directive word, outside any fence
4. `example.md` — a longer fence that *contains* a `mermaid` fence as an example
5. `unclosed.md` — a `mermaid` fence that is never closed, with a directive after it

---

## Scenario 1 — the seeded defect is caught (SC-019)

**This is the scenario that distinguishes *dry* from *blind*.**

1. Run the read axis over the fixture **without** the flag → the broken destination is **not**
   reported. This is today's behaviour and the baseline for scenario 4.
2. Run it **with** the flag → the broken destination **is** reported; the control destination is
   reported as ok.
3. Now repair the fixture (put the file back where the destination points) and re-run → the
   finding disappears.

**Expected**: step 2 reports exactly one broken destination. If step 1 and step 2 agree, the
feature is not wired — a green result there is a false pass, not a success.

---

## Scenario 2 — nothing is written into a diagram (SC-020, SC-023)

1. Take a byte-level snapshot of the fixture tree.
2. Run the read axis **in its writing mode**, with the flag on, over a tree whose only anchorable
   candidates are inside the diagram.
3. Re-snapshot and diff.

**Expected**: **no diff at all.** A single byte of change here is a corrupted diagram, because the
anchor the axis would write is an HTML comment and a diagram renders it as content.

4. Repeat with a file that has *both* a prose link and a diagram destination.

**Expected**: the prose link is anchored, the diagram is untouched.

---

## Scenario 3 — the write operations are unaffected (FR-053)

1. Run repair and robustify with `--write` over the fixture, flag on and flag off.
2. Byte-diff every fenced region.

**Expected**: identical in all four combinations. FR-015 is not amended by this feature, and this
is the check that says so out loud.

---

## Scenario 4 — disabled means byte-identical (SC-018)

1. Run the full read axis over the fixture with the current release, capture the output.
2. Run the same command on this branch, flag absent.
3. Diff the two outputs.

**Expected**: identical, including exit code. This is what makes the feature safe to ship into
fail-closed gates that have not opted in.

---

## Scenario 5 — precision: no false findings (SC-021)

Run with the flag on and confirm **zero** findings from:

| Fixture | Why it must stay silent |
|---|---|
| the diagram comment line | a comment is not a directive (FR-056) — and this case is real, not hypothetical |
| the callback binding | it carries no destination (FR-057) |
| `prose.md` | outside any region: unreachable by construction |
| the `mermaid` fence nested in `example.md` | the outer fence wins; the inner text is never scanned |

**Expected**: the only findings in the whole run are the ones scenario 1 put there.

---

## Scenario 6 — the unclosed fence (FR-016, inherited)

Run with the flag on over `unclosed.md`.

**Expected**: the region runs to end of file and the directive after the opener is recognised. This
behaviour is **inherited**, not implemented here — the scenario exists to prove the region
computation was reused rather than re-implemented (FR-054). If this fails, a second notion of
"fenced block" has crept in.

---

## Scenario 7 — a repository that never opted in (SC-022)

Run every command with no flag and no configuration key.

**Expected**: same output, same exit code, and **no network request** attributable to a diagram
destination.

---

## What this guide deliberately does not do

- It does not check that a real remote destination resolves. That is the existing axis's job and
  its tests inject a fetcher rather than touching the network.
- It does not measure performance. The relevant guarantee is *no added work when disabled*, which
  scenario 4 covers by observation rather than by timing.
