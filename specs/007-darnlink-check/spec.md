# Feature Specification: `darnlink check` — run repair + robustify in one pass

**Feature Branch**: `007-darnlink-check`

**Created**: 2026-07-17

**Status**: Draft

**Input**: A quality gate must verify **both** that existing robust links are not broken (repair) **and**
that every anchorable plain link is robust (robustify). These are two independent checks; consumers
today run them as two separate invocations wired by hand in each repo.

> **Naming (resolved).** Proposed as `gate`; renamed to **`check`** on the constitution review. darnlink
> *checks and reports* (read-only); it is the **consumer** (the CI job / pre-commit hook acting on the
> exit code) that decides to *block* — that is the "gate". "gate" is also the orchestration concept the
> unification agreement assigns to the downstream toolbelt recipe (staged scope, CI-vs-local,
> excludes-policy), and it is the very word Principle II names as the predecessor's fatal incident. So
> the vocabulary follows the architecture: **darnlink `check`s; the consumer gates.** See §Naming.

## The problem: "strict is not a superset of repair" — and everyone rediscovers it

`darnlink . --robustify` (strict) and `darnlink .` (repair) detect **disjoint** failures:

- **repair** catches robust links whose target moved (broken) + invalid YAML frontmatter.
- **robustify** catches plain links to an anchorable target that were never anchored.

`--robustify` does **not** report a broken robust link; `darnlink .` does not report an un-anchored
plain link. A gate that runs only one is blind to the other. This has bitten real repos: gate
wrappers that ran only `--robustify` silently let broken links through until someone noticed the two
modes are complementary (documented across the downstream sessions on 2026-07-17). Each consumer
re-encodes "remember to run both" in its own wrapper, and the wrappers drift.

## The feature

A single dry-run subcommand that runs **both** checks over a tree and reports a combined result with
a **distinguishable exit code**, so a CI/pre-commit gate is one command that cannot forget a half.

```
darnlink check [PATH] [--exclude … --ignore-block … --json]
```

It is **report-only** (never writes — see Constitution Check), builds the UUID index **once** (both
checks share it), and exits with a code that says *which* axis failed.

### Exit codes (the point of the subcommand)

| Code | Meaning |
|---|---|
| 0 | clean — both checks pass |
| 2 | **integrity** failure — broken/unresolvable robust links or invalid frontmatter (the repair axis) |
| 3 | **strict** failure — anchorable plain links left un-anchored (the robustify axis) |
| 1 | usage/error (bad args, unreadable path) |

Integrity (2) takes precedence over strict (3) when both fail — a broken link is more urgent than an
un-anchored one. The consumer can branch on the code; a human reads the same distinction in the report.

## Constitution Check *(mandatory)*

Reviewed against the constitution (verdict on 2026-07-17: green on substance, `check` over `gate`).

- **P-II (Safe by Default / Dry-Run First):** `check` **never writes** — there is no `--write` path on
  it. It runs the existing read-only checks and mutates nothing. The predecessor's incident was
  *silent writing during indexing*; here writing is structurally impossible. ✅
- **P-I (Single Responsibility — Links & UUIDs Only, NON-NEGOTIABLE):** `check` does **only** the two
  operations darnlink already owns (repair + robustify). No external state: no config file, no
  allowlist, no git awareness, no document semantics. The "Check result" is *a view over the existing
  repair and robustify finding sets, not a new model*. Orchestration (excludes-as-policy,
  staged-vs-repo scoping, CI-vs-local split) stays **out** of darnlink, in the toolbelt recipe. `check`
  never learns *which files are generated* (that is the `<!-- darnlink-ignore-links -->` marker's job)
  and never reads a list of anything. ✅
- **P-IV (Deterministic):** exit code is a pure function of the tree. ✅

### Naming

`check` over `gate`, on three architectural grounds (reviewer's call, recorded):
1. **Vocabulary follows architecture.** The agreement assigns the *gate* (orchestration) to the
   toolbelt; darnlink provides the primitive. darnlink `check`s; the toolbelt turns `darnlink check`
   into a gate.
2. **"gate" carries the predecessor's risk identity** — Principle II names the "gate incident" as its
   fatal moment. Reusing the word invites the identity ("a gate needs config, needs staged, …").
3. **`check` is honest about responsibility.** darnlink checks and reports (read-only); *blocking* is
   the consumer's decision (the CI/hook acting on the exit code). `check` names darnlink's job; `gate`
   names the consumer's.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `darnlink check PATH` MUST run the repair check and the robustify check over PATH in a
  single process, building the UUID index once.
- **FR-002** It MUST be report-only: no flag on `check` writes to disk; `--write` is not accepted.
- **FR-003** Exit code MUST be 0 (clean), 2 (integrity failure), 3 (strict-only failure), 1 (usage).
  Integrity precedence over strict when both fail.
- **FR-004** It MUST honour `--exclude`, `--ignore-block`, and the in-file markers exactly as the
  existing commands do (same scan surface), so a repo's check result matches its direct-command result.
- **FR-005** `--json` MUST emit both axes' findings in one document, each finding tagged by `kind`, so
  a machine can separate integrity from strict without re-running.
- **FR-006** Human output MUST state both axes' results explicitly — never a silent pass on one axis
  (Constitution II: no silent skips).

### Key Entities

- **Check result:** `{ integrity: {failures…}, strict: {failures…}, exit_code }` — a view over the
  existing repair and robustify finding sets, not a new model.

## Acceptance

- A tree with a broken robust link and no un-anchored plain links → exit **2**.
- A tree with an un-anchored anchorable plain link and no broken links → exit **3**.
- A tree with both → exit **2** (integrity precedence), report shows both.
- A clean tree → exit **0**.
- `darnlink check` and running `darnlink .` then `darnlink . --robustify` MUST agree on pass/fail per
  axis (same checks, one index build).
- No file on disk changes across any `check` invocation (assert mtimes unchanged).

## Out of scope (explicitly, per the unification agreement)

- `--staged` / git-awareness → separate spec (008).
- Per-repo excludes-as-config / `.darnlink.toml` → separate spec; NOT part of `check`.
- Generated-file handling → already solved by `<!-- darnlink-ignore-links -->` (spec 006). `check`
  never lists generated files.
