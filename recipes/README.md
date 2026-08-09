---
uuid: b4e6058b-4af0-4d23-a826-975a8fc78e6f
---

# darnlink-gate — the one generic darnlink quality-gate recipe

The **`darnlink-gate`** script here (+ `.ps1` for Windows) is the **single** orchestration around
[darnlink](https://github.com/txemi/darnlink) for every repo that uses it. darnlink itself is a pure
link tool — it checks and reports, and deliberately knows nothing about gates, git, excludes-policy,
or CI (its Constitution). All that orchestration used to be copy-pasted into each repo's `*_gate.sh`
and drifted (the "strict ⊇ repair" myth, `ignore-file` vs `ignore-links`, un-pinned refs). This recipe
is that orchestration in one place; a consumer carries only a tiny config + a 3-line hook.

## What it does (read-only — never writes)

- Runs darnlink at a **pinned ref** (deterministic).
- `mode` picks which axes gate — **three rungs of a one-way ratchet** (each a superset of the one
  above, so raising `mode` can only tighten):
  - `mode=repair` → **integrity only** — a strict-only failure (`3`) is clean (repos that don't
    robustify their links yet).
  - `mode=check` → integrity **+** strict (the default). Runs `darnlink check` (stable `0/2/3`).
  - `mode=max` → integrity + strict **+ create-frontmatter** = **fail-closed links**: a link to a file
    with **no `uuid`** fails the gate. `check` has no create-frontmatter axis and the bare
    `darnlink . --robustify --create-frontmatter` has no integrity axis, so `max` runs **both** dry-run
    passes (a true superset of `check` — it can't silently drop broken robust links).
    **Whole-repo only** — the staged pre-commit stays at strict on purpose (fast); the whole-repo wall
    (pre-push / CI) is where `max` is enforced. See [`docs/elevating-your-link-gate.md`](../docs/elevating-your-link-gate.md) <!-- uuid: e95eaed1-9866-4c48-a0d7-99a6382f5bf9 -->.
- `dangling` (opt-in, **default `off`**) → gate on links whose target does not exist (feature 015).
  A **separate axis, never folded into `mode`**, and that is the point: every consumer already carries
  years of these, so folding them into `check`/`max` would turn each gate red on upgrade and the only
  escape would be *lowering* `mode` — a ladder you can only climb by first stepping down is not a
  ladder. Four settings:

  | `dangling` | Behaviour |
  |---|---|
  | `off` *(default)* | not gated, not listed. Upgrading the pin changes no verdict. `check` still states the **count** on one line, so a repo learns it has dead links. |
  | `warn` | listed, never fails. The honest way to see the backlog before gating it. |
  | `added-lines` | fails only on findings on lines **this commit adds** (`scope=staged`). The adoption rung. |
  | `repo` | fails on **any** finding. The wall, for a repo already at zero. |

  **Why `added-lines` and not per-file:** per-file was tried and is not enough — editing one line of a
  README that already carries old danglers blocks the commit, which pushes people to `--no-verify`,
  and a gate people bypass gates nothing. The added lines come from `git diff --cached -U0`; git lives
  here, not in darnlink (spec 008, Option B).

  ⚠️ **Not yet in `darnlink-gate.ps1`.** The Windows recipe ignores the `dangling` key, so a
  Windows-only surface silently does not gate this axis. Being explicit rather than letting the
  difference be discovered: on a repo that gates on both, POSIX gates it and Windows does not.

- `scope=repo` → judge the whole tree (**the wall — use in pre-push & CI**).
  `scope=staged` → judge only the files you're committing (**multi-session pre-commit**, so a
  teammate's in-flight plain link doesn't block your commit). It filters `darnlink check --json` by
  `git diff --cached` — **darnlink stays git-agnostic; the git lives here** (darnlink spec 008,
  Option B).
- Fails **open** on a network/uvx error (offline commits aren't bricked) — **UNLESS fail-closed is on**.
  ⚠️ **In CI set `DARNLINK_GATE_FAIL_CLOSED=1`** (or `"fail_closed": true`): there the gate *is* the
  wall, and failing open on a transient network/PyPI hiccup means a **GREEN build with zero files
  validated**. Prefer the env var over the json key — reading the json needs `python3`, and
  "python3 missing" is one of the very cases fail-closed exists to catch.
- **Refuses `--write`** (this gate never mutates; robustify by hand).

Exit: `0` clean · `2` integrity failure · `3` strict-only failure · `1` usage / `max`-mode findings ·
`4` could-not-gate (fail-closed only).

## Adopt it in a repo (the wall in 4 pieces)

The gate runs at three layers, each at the scope that fits — **deliberate, not redundant** (see
[`docs/elevating-your-link-gate.md §7`](../docs/elevating-your-link-gate.md) <!-- uuid: e95eaed1-9866-4c48-a0d7-99a6382f5bf9 -->): staged & fast locally,
whole-repo where it's the wall.

**1. Config** — `darnlink-gate.json` at the repo root (all keys optional):

```json
{
  "ref": "git+https://github.com/txemi/darnlink@v0.7.0",
  "excludes": ["secrets", "external_repos"],
  "ignore_blocks": ["txmd-autogrid"],
  "mode": "check",
  "scope": "repo"
}
```

**Repos with a big `mirrors/` tree** (a faithful local copy of an external system) usually want a
fourth shape: enforce robustify + the create-readme axis, but skip README-creation *under the mirror*
(you don't invent a README for someone else's export) — while still validating links that point INTO
the mirror. Two keys make that expressible:

```json
{
  "ref": "git+https://github.com/txemi/darnlink@v0.18.0",
  "mode": "check",
  "create_readme": true,
  "create_readme_excludes": ["mirrors"],
  "excludes": [".pytest_cache", "clones", "output"]
}
```

- `create_readme` (any mode, since v0.18.x) — a plain link to a folder with no README fails the gate.
  It runs as its own dry-run pass filtered to the `create_readme` findings, so it now adds the folder
  axis on top of `mode=check`/`repair`, not only `mode=max`. (In `mode=max` with **no**
  `create_readme_excludes` it stays folded into the max robustify pass exactly as before.)
- `create_readme_excludes` (default `[]`) — extra directory globs applied **only** to the create-readme
  pass, on top of `excludes`. It suppresses README-creation for those paths **without** dropping them
  from the integrity/robustify axes (inbound links into a mirror must still validate). Absent = old
  behavior.

**2. Pre-commit** (staged, fast) — so parallel sessions don't block each other; the repo-wide wall is
pieces 3–4:

```bash
#!/usr/bin/env bash
# hooks/pre-commit.d/NN-darnlink
exec env DARNLINK_GATE_SCOPE=staged darnlink-gate
```

**3. Pre-push** (whole repo) — `git push` is deliberate and infrequent → no deadlock. This is the
**local wall** that stops anything broken from leaving your machine, even if CI is down:

```bash
#!/usr/bin/env bash
# .git/hooks/pre-push  (or hooks/pre-push if you version your hooks)
exec darnlink-gate            # scope=repo from config
```

**4. CI** (GitHub Actions / Jenkins, whole repo) — the unbypassable server-side wall (catches even a
`--no-verify`). **Set fail-closed**, or a network hiccup gives you a green build that validated nothing:

```yaml
- uses: astral-sh/setup-uv@v5
- run: darnlink-gate            # scope=repo from config
  env:
    DARNLINK_GATE_FAIL_CLOSED: "1"   # ← the wall must fail closed
```

> On a private repo where hosted CI minutes are billed or branch protection is unavailable, a
> **self-hosted runner** (e.g. a home CI box) is the natural home for piece 4 — same check, no billing.

**Complete, copy-paste versions of all four** live in [`examples/`](examples/) <!-- uuid: f8da8344-8293-4c05-b154-8bdb088adddf --> — whole working files,
not snippets to assemble (assembling the CI one wrong yields a wall that fails *open*).

**Getting the script.** It lives here — `recipes/darnlink-gate` in the **public** darnlink repo — so
any CI can fetch it **without a token** (no private checkout, no cred):

```bash
curl -sSL https://raw.githubusercontent.com/txemi/darnlink/v0.7.0/recipes/darnlink-gate -o darnlink-gate
chmod +x darnlink-gate
```

Pin the tag (`v0.7.0`) so the gate is deterministic. Windows agents fetch `darnlink-gate.ps1` the same
way. Locally, drop it on your `PATH` (e.g. `~/.local/bin`).

## Notes

- **Generated files** are handled by the `<!-- darnlink-ignore-links -->` marker (emitted by the
  generator), **not** by this recipe — the recipe never lists files. See darnlink `FORMAT.md §5`.
- Per-repo differences (ref, excludes, mode, scope) live entirely in `darnlink-gate.json`; the logic
  is identical everywhere. When darnlink changes a recommendation, fix it **here**, not in N repos.
- Supersedes the old per-repo `tools/darnlink_gate.sh` / `scripts/darnlink_gate.ps1` /
  `darnlink_robustness_check.py` wrappers each repo used to carry.
- **This is a reference recipe, not part of the darnlink CLI/package.** The tool itself stays "links &
  UUIDs only" (its Constitution); this script only *orchestrates* it (pinned ref, both checks, staged
  scope, fail-open). darnlink `check`s; the recipe wires it into your gate.
