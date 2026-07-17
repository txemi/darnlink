# darnlink-gate — the one generic darnlink quality-gate recipe

The **`darnlink-gate`** script here (+ `.ps1` for Windows) is the **single** orchestration around
[darnlink](https://github.com/txemi/darnlink) for every repo that uses it. darnlink itself is a pure
link tool — it checks and reports, and deliberately knows nothing about gates, git, excludes-policy,
or CI (its Constitution). All that orchestration used to be copy-pasted into each repo's `*_gate.sh`
and drifted (the "strict ⊇ repair" myth, `ignore-file` vs `ignore-links`, un-pinned refs). This recipe
is that orchestration in one place; a consumer carries only a tiny config + a 3-line hook.

## What it does (read-only — never writes)

- Runs darnlink at a **pinned ref** (deterministic).
- `mode=check` → `darnlink check` (**both** axes: integrity + strict, exit `0/2/3`).
  `mode=repair` → `darnlink .` (integrity only — for repos that don't robustify their links yet).
- `scope=repo` → judge the whole tree (**the wall — use in CI**).
  `scope=staged` → judge only the files you're committing (**multi-session pre-commit**, so a
  teammate's in-flight plain link doesn't block your commit). It filters `darnlink check --json` by
  `git diff --cached` — **darnlink stays git-agnostic; the git lives here** (darnlink spec 008,
  Option B).
- Fails **open** on a network/uvx error (offline commits aren't bricked; CI is the backstop).
- **Refuses `--write`** (this gate never mutates; robustify by hand).

Exit: `0` clean · `2` integrity failure · `3` strict-only failure · `1` usage.

## Adopt it in a repo (3 pieces)

**1. Config** — `darnlink-gate.json` at the repo root (all keys optional):

```json
{
  "ref": "git+https://github.com/txemi/darnlink@v0.4.0",
  "excludes": ["secrets", "external_repos"],
  "ignore_blocks": ["txmd-autogrid"],
  "mode": "check",
  "scope": "repo"
}
```

**2. Pre-commit** — a 3-line `conf.d` fragment (staged scope, so parallel sessions don't block each
other; the repo-wide wall stays in CI):

```bash
#!/usr/bin/env bash
# hooks/pre-commit.d/NN-darnlink
exec env DARNLINK_GATE_SCOPE=staged darnlink-gate
```

**3. CI** (GitHub Actions / Jenkins) — the wall, whole-repo:

```yaml
- uses: astral-sh/setup-uv@v5
- run: darnlink-gate            # scope=repo from config
```

**Getting the script.** It lives here — `recipes/darnlink-gate` in the **public** darnlink repo — so
any CI can fetch it **without a token** (no private checkout, no cred):

```bash
curl -sSL https://raw.githubusercontent.com/txemi/darnlink/v0.4.0/recipes/darnlink-gate -o darnlink-gate
chmod +x darnlink-gate
```

Pin the tag (`v0.4.0`) so the gate is deterministic. Windows agents fetch `darnlink-gate.ps1` the same
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
