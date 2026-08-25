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

- `web` (opt-in, **default off**, `mode=max` only) → adds a whole-repo `web-check --online` pass:
  cross-repo Markdown links to **other GitHub repos** must resolve to the destination file's `uuid`,
  read over the network and anchored with `<!-- web-uuid: X -->`.
  ⚠️ **Both public and private destinations need `GITHUB_TOKEN`** — private ones for permission,
  **public ones for quota** (anonymous API = 60/h per public IP, shared by everyone behind the same
  NAT). Without it they come back `web_unverifiable`, which is a warning and reads like *nothing to
  check*: **that is a false green**, because an un-anchored web link is only discoverable if the
  destination can be READ. Measured on one repo, same tree, same day: without token `rc=0`, with
  token `rc=3`. Quote the token condition next to any web figure or it isn't comparable.

- `own_web` / `own_web_from_origin` / `own_web_max` (opt-in, **need `web`**) → feature 016. A web
  destination owned by **you** whose `.md` has no `uuid` stops being *someone else's problem* and
  **fails the gate**: it is a two-line edit in a repo you control, so it is fixable, which is the
  whole difference from an external link.

  | key | Value | Meaning |
  |---|---|---|
  | `own_web` | list of GitHub owners | the owners you control |
  | `own_web_from_origin` | bool | also count this repo's `origin` owner. A **separate key, not a sentinel** in the list, so an owner literally called `origin` stays expressible |
  | `default_branch` | string | the repo's default branch, e.g. `main`. **Declare it in CI**: a multibranch PR job fetches only the pull ref, so there is no `origin/HEAD`, and `ls-remote` usually has no credentials there — without this the pending-vs-broken rung goes INERT exactly where it is needed. It says so on stderr when it does |
  | `own_web_max` | int | a budget, so the rung is adoptable before the repo reaches zero. **Non-numeric counts as ABSENT, never as infinite** — widening an allowance is the one direction a config typo must not be able to go |

- `include_mermaid` (opt-in, **needs `web`**) → feature 017. A `mermaid` diagram carries its
  destinations in `click` directives, which sit inside a fenced block and are therefore invisible to
  every axis. With this key the **read** axis sees them; the write operations still never look
  inside a fence.

  | key | Value | Meaning |
  |---|---|---|
  | `include_mermaid` | bool | watch the destinations a diagram's `click` directives carry |

  **Absent means off, per repository** — on purpose. Measured across a fleet, switching this on
  exposed 33 own-repository destinations in one repo (all valid, so it goes green on day one) and
  over two thousand third-party ones in others, which cannot be fixed from where they are reported.
  A fail-closed gate that switches itself on everywhere is how every push breaks at once.

  ⚠️ These links are **report-only and never anchored**, so a diagram destination that stays plain
  forever is a normal state, not a defect: the anchor is an HTML comment and a diagram renders it as
  a node rather than treating it as a comment.

  A misconfiguration (a budget with no owners, an empty owner name, `own_web_from_origin` in a tree
  with no GitHub `origin`) exits `1`, and the recipe reports it as **likely-config** rather than as a
  verdict about the repository — but **only when this run actually passed an `own_*` flag**, because
  exit `1` is not exclusively a usage error (`uvx` and an uncaught exception use it too). Under
  `fail_closed` it still fails, with `4`: in CI an axis that could not run is not a pass.

  ⚠️ **`darnlink-gate.ps1` implements these keys, but its web pass still `exit`s the moment it
  finishes**, so on Windows the create-readme and dangling axes do not run after a web pass — the
  bug the POSIX recipe was fixed for. Same caveat as `dangling` below: stated rather than left to be
  discovered.

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
  "ref": "git+https://github.com/txemi/darnlink@vX.Y.Z",
  "recipe_sha256": "<sha256 of recipes/darnlink-gate at that ref>",
  "excludes": ["secrets", "external_repos"],
  "ignore_blocks": ["txmd-autogrid"],
  "mode": "check",
  "scope": "repo"
}
```

⚠️ **`recipe_sha256` is the only key here the recipe never reads.** Every other key is consumed by
`darnlink-gate` once it is already running; this one is consumed by whatever **fetches** it, *before*
it runs. That asymmetry is the whole point, and it is why the key was easy to overlook: a CI surface
that downloads this script and executes it cannot ask the script whether the download was genuine.
See **"Verify what you download"** below for how to compute and re-seal it.

⚠️ **`vX.Y.Z` is a placeholder, and it is the one thing here you must not copy verbatim.** Resolve it
when you paste — `gh release view -R txemi/darnlink --json tagName -q .tagName` — because this is the
*only* pin: every CI surface derives from it. A concrete tag printed in a document is how the last
one rotted; it sat at `v0.7.0` through **23** releases, quietly recommending a gate far behind the one
documented beside it. The recipe itself says the same thing about its own header, for the same reason.

**Repos with a big `mirrors/` tree** (a faithful local copy of an external system) usually want a
fourth shape: enforce robustify + the create-readme axis, but skip README-creation *under the mirror*
(you don't invent a README for someone else's export) — while still validating links that point INTO
the mirror. Two keys make that expressible:

```json
{
  "ref": "git+https://github.com/txemi/darnlink@vX.Y.Z",
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
# Derive the version from the `ref` you already declared — do NOT write a second copy of it here.
VER=$(python3 -c 'import json;print(json.load(open("darnlink-gate.json"))["ref"].rsplit("@",1)[1])')
curl -fsSL "https://raw.githubusercontent.com/txemi/darnlink/$VER/recipes/darnlink-gate" -o darnlink-gate
# VERIFY BEFORE YOU MAKE IT EXECUTABLE — see "Verify what you download" below.
WANT=$(python3 -c 'import json;print(json.load(open("darnlink-gate.json")).get("recipe_sha256",""))')
[ -n "$WANT" ] && { echo "$WANT  darnlink-gate" | sha256sum -c - || exit 1; }
chmod +x darnlink-gate
```

**One pin, and it lives in `darnlink-gate.json`.** This block used to hard-code a tag and tell you to
keep it pinned — and that instruction is what rotted: it sat at `v0.7.0` for **23 releases**, quietly
telling every new adopter to install a gate far behind the one documented right above it. Nothing
fails when two copies of a version number drift, so the second copy has to go rather than be kept in
sync. `-f` so a moved or typo'd version is a 404 instead of a file containing the words
"404: Not Found". Windows agents fetch `darnlink-gate.ps1` the same way. Locally, drop it on your
`PATH` (e.g. `~/.local/bin`).

## Verify what you download

Every CI surface in this page ends with the same three lines: **fetch a script over the network, mark
it executable, run it.** A pin does not make that safe. A tag is a mutable pointer — and this recipe
deliberately accepts a branch or a SHA too — so the pin says *which name* you asked for, never *which
bytes* you got. `recipe_sha256` is the only statement about the bytes.

Compute it once, at the ref you pinned:

```bash
VER=$(python3 -c 'import json;print(json.load(open("darnlink-gate.json"))["ref"].rsplit("@",1)[1])')
curl -fsSL "https://raw.githubusercontent.com/txemi/darnlink/$VER/recipes/darnlink-gate" | sha256sum
```

and put the digest in `darnlink-gate.json` next to `ref`. The shipped examples then compare it
**before** `chmod +x`, and — just as importantly — **say so when the key is absent** rather than
staying quiet, because silence at that spot is indistinguishable from "verified".

> ### ⚠️ The rule that actually bites: `ref` and `recipe_sha256` move TOGETHER
>
> They are two halves of one statement. Bump the pin and leave the digest behind, and the next build
> fails with a checksum mismatch that *looks* like tampering. Keep them adjacent in the file, and
> re-seal in the same commit that bumps the ref.
>
> This is why the examples' error message names **three** causes and puts the mundane one first. An
> earlier wording offered only "the tag moved, or the fetch was tampered with" — both catastrophic,
> neither of them what happens in practice. A message that only offers alarming explanations turns a
> maintenance slip into a suspected supply-chain attack, and someone pays for that in wasted alarm.

**Adopting this into an existing gate?** The two lines are additive and the key is optional, so a
repo that has not sealed a digest yet keeps working exactly as before — it just starts warning that
its download is unverified. That is deliberate: a hard failure on arrival would get the gate deleted
rather than sealed.

⚠️ **Fixing this file does not fix the copies.** These are copy-paste templates: every surface that
already pasted the older version still runs unverified, and nothing here reaches them. Measured once
across a private fleet: the wall was standing on the self-hosted-CI and local-script surfaces and
**absent from every hosted-CI one**, in every repo — so it was not a stray bad copy, it was one whole
axis that never had the check. When you take this update, grep your own surfaces rather than trusting
a list.

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
