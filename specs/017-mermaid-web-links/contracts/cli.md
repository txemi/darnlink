# Phase 1 — Interface contract

This is a CLI library. Its contract is the command surface: what a user can ask for, what comes
back, and what the exit code means. Nothing here is a new subcommand — the feature is one switch on
an axis that already exists.

---

## 1. The switch

A single opt-in flag on the **read** axis, default **off**.

| | |
|---|---|
| **Where it applies** | the web-check command, in **both** of its paths — the online check and the offline listing |
| **Where it does NOT apply** | the core command (repair / robustify). Offering it there would imply the write axis can honour it; it cannot, and must not |
| **Default** | off. With the flag absent, output is byte-identical to the current release (SC-018) |
| **Combining** | composes with the existing owner flags and ignore-block markers exactly as ordinary web links do; it changes *which links exist*, not how they are judged |

**Naming principle**: the flag says *what becomes visible*, not *how it is parsed*. A user
switching it on is choosing to watch their diagrams, not choosing a parsing strategy.

### The recipe layer

The gate recipe published with this project reads a JSON configuration whose keys map onto these
flags (`web`, `own_web_from_origin`, and friends). This feature adds **one key**, defaulting to
absent-means-off, mapping to the flag above. A repository that does not add the key is unaffected —
which is the point: rolling this out across a fleet is opt-in **per repository**, one line at a
time (FR-052, SC-022).

---

## 2. What comes back

A recognised diagram destination is reported **exactly like any other web link**: same finding
kinds, same message shapes, same JSON fields. There is no diagram-specific finding kind, because
inventing one would force every consumer of the report to learn a new case for no benefit
(research R3).

**The one visible difference** is what *cannot* happen to it:

| Finding kind | Ordinary web link | Diagram destination |
|---|---|---|
| reported as ok / not-found / mismatch / unverifiable | yes | **yes, identical** |
| judged by the own-repository strictness rule | yes | **yes, identical** |
| **anchored** (rewritten with a trailing anchor comment) | yes, under the writing mode | **never** (FR-060) |

Under the writing mode, an ordinary plain link that could be anchored is anchored; a diagram
destination in the same file is reported and **left alone**. The report must make that legible
rather than silently dropping it — a destination that is watched but never rewritten is a normal,
permanent state here, not a failure.

---

## 3. Exit codes

**Unchanged.** This feature adds no exit code and redefines none. A diagram destination
contributes to the existing codes exactly as the equivalent prose link would.

The consequence is deliberate and worth stating plainly: in a repository that opts in **and**
enables the own-repository strictness rule, a dead destination inside a diagram will **fail the
gate**. That is the entire purpose — it is the failure that does not happen today.

---

## 4. Compatibility

| Question | Answer |
|---|---|
| Does an existing invocation change? | No. Without the new flag, nothing changes anywhere |
| Does an existing configuration change? | No. The new key is absent-means-off |
| Does the written format change? | No. Nothing new is ever written; the anchor format is untouched |
| Does the report schema change? | No new kinds and no removed fields |
| Can a repository be broken by upgrading? | No. Breaking requires an explicit opt-in, and the measurement says the first repository to opt in goes green on day one |
