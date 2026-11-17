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

  `darnlink-gate.ps1` gates it too, with the same settings and budget (from 0.31; before, it
  ignored the key).

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

- `forgejo_web` (opt-in, **needs `web`**) → feature 018. Links to a **self-hosted Forgejo** are
  only recognised once the instance is declared; then its file links
  (`/<owner>/<repo>/src|raw/branch|tag|commit/<ref>/<path>`) are verified and anchored exactly like
  GitHub's, through its raw API (`/api/v1/repos/<owner>/<repo>/raw/<path>?ref=<ref>`).

  | key | Value | Meaning |
  |---|---|---|
  | `forgejo_web` | list of strings | **one entry per instance**; if it answers to several names, list them all in that entry, comma-separated, **with scheme and port**: `"https://forge.example.test,http://forge.lan.example.test:3000"` |

  Links are recognised under **any** of an instance's names, and fetched through the **first
  name that is reachable** from where the gate runs — a laptop and a build agent often resolve
  different names for the same server. A name that is unreachable is skipped for the rest of the
  run. A bare host is refused rather than completed with a guessed scheme.

  The token is **`FORGEJO_TOKEN`** (or the file in `DARNLINK_GATE_FORGEJO_TOKEN_FILE`, default
  `~/.config/forgejo_token_ro`), sent as `Authorization: token …`. It is never sent to GitHub, and
  `GITHUB_TOKEN` is never sent to a Forgejo. `own_web` owners apply on a declared Forgejo too, and
  the pending-on-default-branch rung recognises this repository there through **any git remote**
  whose host is one of the instance's names — so a repo moving between forges keeps it.

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

  The web pass falls through to the create-readme and dangling axes in both recipes (from 0.31,
  the `.ps1` no longer `exit`s after it).

- `scope=repo` → judge the whole tree (**the wall — use in pre-push & CI**).
  `scope=staged` → judge only the files you're committing (**multi-session pre-commit**, so a
  teammate's in-flight plain link doesn't block your commit). It filters `darnlink check --json` by
  `git diff --cached` — **darnlink stays git-agnostic; the git lives here** (darnlink spec 008,
  Option B). If git cannot list the staged files (unreadable index, git missing), that is "could not
  look", not "nothing staged": the gate stops like any other axis that could not run (`4` under
  fail-closed, a skip otherwise), in both recipes. The same goes for reading the lines each file adds
  (`dangling=added-lines`) and for running outside a git repository.
  When a strict failure prints the fix command to paste (`git ... diff --cached --name-only | uvx ...
  --only-from -`), note that on **Windows PowerShell 5.1** a pipe between two native programs
  re-encodes the text through `$OutputEncoding` (ASCII), so a non-ASCII file name can reach darnlink
  mangled; set `$OutputEncoding = [Text.UTF8Encoding]::new($false)` first, or use PowerShell 7.4+.
  The gate's own check is not affected: it reads the names as UTF-8.
- Fails **open** on a network/uvx error (offline commits aren't bricked) — **UNLESS fail-closed is on**.
  ⚠️ **In CI set `DARNLINK_GATE_FAIL_CLOSED=1`** (or `"fail_closed": true`): there the gate *is* the
  wall, and failing open on a transient network/PyPI hiccup means a **GREEN build with zero files
  validated**. Prefer the env var over the json key — reading the json needs `python3`, and
  "python3 missing" is one of the very cases fail-closed exists to catch.
- **Refuses `--write`** (this gate never mutates; robustify by hand), and forwards **no other
  command-line argument** to darnlink: the gate is configured by `darnlink-gate.json` and the
  environment only, in both recipes (the `.ps1` used to pass its arguments to the whole-repo passes).
  Such arguments are **ignored with a warning on stderr, not refused**: a `pre-commit` hook with
  `pass_filenames: true` hands the gate every staged file name, and exiting 1 on those would break
  every commit of a setup that works. Set `pass_filenames: false`, and put policy in the config file.
- **Stops on a config it cannot trust** (exit `1`, in both fail modes, before running anything): a
  `darnlink-gate.json` that is not valid JSON (the `.ps1` used to run with every default, in
  silence), a file whose top level is not an object (`[1]`, `"x"`, `3`: both recipes used to run
  with every default), and a flag (`fail_closed`, `web`, `own_web_from_origin`, `include_mermaid`,
  `create_readme`) whose value is not on the closed list, compared in any case: `true`, `1`, `yes`,
  `on` / `false`, `0`, `no`, `off`, or absent. `"disabled"` used to turn the flag **on**.
  On Windows PowerShell 5.1 the JSON check is laxer: beyond what its own parser rejects, it only
  catches a trailing comma (PowerShell 7 parses as strictly as bash).
- **Both recipes run the same gate** (from 0.31). `darnlink-gate.ps1` follows the bash recipe:
  `mode` and `scope` are case-sensitive (`"MAX"` runs `check`, as it does in bash), and it reads
  `dangling`, `dangling_max`, `default_branch` and `create_readme_excludes` and runs
  `create_readme` in any mode. `tests/test_recipe_parity.py` holds one table of configs that both
  must follow; its PowerShell half runs where `pwsh` or `powershell` is on PATH.

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
  "recipe_sha256": "<64 hex chars — RESOLVE THIS, see below; do not paste it as-is>",
  "excludes": ["secrets", "external_repos"],
  "ignore_blocks": ["txmd-autogrid"],
  "mode": "check",
  "scope": "repo"
}
```

**Check it.** `darnlink gate-config` (from 0.31) reads `darnlink-gate.json` and prints a
`darnlink: warning:` for each key the recipes do not read and each value they would misread: a flag
set to `"disabled"` turns it ON, `"exclude"` instead of `"excludes"` configures nothing. It exits 0,
also with warnings; `--strict` makes them exit 1. Both recipes run it on every pass, after the
pre-flight, and print its warnings without changing the verdict; a pinned `ref` older than 0.31 has
no such command, and the gate says so in one line and goes on. The published schema of the file is
`src/darnlink/schemas/v1/gate_config.schema.json`, for an editor (`"$schema"`) or a schema gate. It
describes the **canonical form**: lower-case flag and enum values, which is stricter than what the
recipes accept. Besides the keys below, it allows `$schema`, `ref_comment` and `ref_tag`, and any
key starting with `_` as a note.

⚠️ **`recipe_sha256` is a placeholder too, and unlike `ref` it does not fail cleanly.** A wrong
`ref` is a 404 and `curl -f` says so; a wrong digest is a *checksum mismatch*, and the first cause
that message names is "someone bumped `ref` without re-sealing" — which is not what happened. The
templates therefore check the SHAPE first (64 lowercase hex) and say "you pasted the placeholder"
rather than crying tampering. Resolve it with the command in **"Verify what you download"** below,
or drop the key while you adopt: absent is honest, wrong is misleading.

⚠️ **`recipe_sha256` is read by the INSTALLED recipe, to run the one this repo pins.** The script is
installed once per machine (a workstation's deploy, a CI agent's IaC) and every repo there calls it,
but each repo pins its own version. So the running copy hashes itself and compares with
`recipe_sha256`: equal, it runs; different, it fetches `recipes/darnlink-gate` at the version in
`ref`, verifies it against the key, caches it and execs it with the same arguments, environment and
directory. One call, `darnlink-gate`, in the hook and in CI, and every repo is gated by the recipe it
chose. What a downloaded script still cannot do is vouch for its own download, which is why the check
runs in the trusted, installed copy *before* the exec, and why a CI surface that downloads the
script itself still compares the digest before `chmod +x`. See **"Verify what you download"** below
for how to compute and re-seal it.

The hand-off, in detail:

- **Mismatch after download:** exit 1 on every surface, nothing cached, and the message names the
  mundane cause first (a `ref` bumped without re-sealing). **Fetch fails** (no network, no curl, a
  `ref` with no `@<version>`): a can't-gate, so a skip when fail-open and 4 under fail-closed. A
  **malformed digest** (not 64 hex after folding A-F) is a config error: exit 1.
- **Fails fast:** `curl` with a 10 s connect and 60 s total timeout, and no retry; the message names
  the version and the full URL it tried. An agent without network does not hang a build.
- **Where from:** `$DARNLINK_GATE_RECIPE_BASE/<version>/recipes/darnlink-gate`, the base defaulting to
  GitHub's raw host for this repo (`https://raw.githubusercontent.com/txemi/darnlink/<version>/…`).
  Point it at a mirror where the agents cannot reach GitHub.
- **Cache:** by digest, so a hit is re-hashed rather than trusted. Never a temp directory by default
  (on an agent `/tmp` is often RAM). Order: `DARNLINK_GATE_CACHE` as given; else
  `/var/cache/darnlink-gate` if it exists and is writable (the agent's IaC creates it; the recipe
  never does; `DARNLINK_GATE_SYSTEM_CACHE` moves it); else `${XDG_CACHE_HOME:-~/.cache}/darnlink-gate`,
  refused if that is under `/tmp` or `$TMPDIR`; else a can't-gate that says why. The download goes to
  a temp file in that same directory and is renamed into place only once verified.
- **Loop guard:** the hand-off exports `DARNLINK_GATE_HANDOFF_DONE=1`, so the exec'd copy runs as
  itself. Set it by hand to run the installed copy whatever the pin says.

**The PowerShell twin has its own key, `recipe_ps1_sha256`** (or `$env:DARNLINK_GATE_PS1_SHA256`):
the digest of `recipes/darnlink-gate.ps1` at `ref`. It hands off exactly as above, fetching
`recipes/darnlink-gate.ps1` and caching it as `<digest>.ps1`. It never hands off on `recipe_sha256`,
which is the digest of a different file and would be a permanent mismatch, read as tampering on every
Windows run; with only that key set it says so in one line and runs as installed.

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
WANT=$(printf '%s' "$WANT" | tr 'A-F' 'a-f')   # PowerShell's Get-FileHash returns uppercase
if [ -n "$WANT" ]; then
  case "$WANT" in *[!0-9a-f]*|"") echo "recipe_sha256 is not a digest — did you paste the placeholder?" >&2; exit 1 ;; esac
  echo "$WANT  darnlink-gate" | sha256sum -c - || { rm -f darnlink-gate; exit 1; }
else
  echo "darnlink-gate.json declares no recipe_sha256 — THIS DOWNLOAD IS NOT VERIFIED." >&2
fi
chmod +x darnlink-gate
```

**One pin, and it lives in `darnlink-gate.json`.** This block used to hard-code a tag and tell you to
keep it pinned — and that instruction is what rotted: it sat at `v0.7.0` for **23 releases**, quietly
telling every new adopter to install a gate far behind the one documented right above it. Nothing
fails when two copies of a version number drift, so the second copy has to go rather than be kept in
sync. `-f` so a moved or typo'd version is a 404 instead of a file containing the words
"404: Not Found". Windows agents fetch `darnlink-gate.ps1` the same way — ⚠️ **but `recipe_sha256` does NOT cover it.**
The key is defined as the digest of `recipes/darnlink-gate`; the `.ps1` is a different file with a
different digest: seal it in `recipe_ps1_sha256` (`(Get-FileHash -Algorithm SHA256 darnlink-gate.ps1).Hash.ToLower()`).
Sealing `recipe_sha256` with the `.ps1`'s digest gives a permanent mismatch, and so would the bash
recipe's hand-off. The shipped templates verify only the bash download; a Windows agent that fetches
the `.ps1` itself verifies it against `recipe_ps1_sha256` by its own means, or leaves it unsealed —
knowingly. An installed `.ps1` does that check for you when it hands off. Locally, drop it on your
`PATH` (e.g. `~/.local/bin`).

## Verify what you download

Only piece 4 fetches anything, in both its forms — plus the manual snippet below. All three end
with the same three lines: **fetch a script over the network, mark it executable, run it**. (Pieces 2 and 3
`exec darnlink-gate` off your `PATH` and download nothing, so none of this applies to them.) A pin
does not make the fetching ones safe. A tag is a mutable pointer — and this recipe
deliberately accepts a branch or a SHA too — so the pin says *which name* you asked for, never *which
bytes* you got. `recipe_sha256` is the only statement about the bytes.

Compute it once, at the ref you pinned:

```bash
VER=$(python3 -c 'import json;print(json.load(open("darnlink-gate.json"))["ref"].rsplit("@",1)[1])')
curl -fsSL "https://raw.githubusercontent.com/txemi/darnlink/$VER/recipes/darnlink-gate" \
  | sha256sum | cut -d' ' -f1
```

⚠️ **The `cut` is not decoration.** `sha256sum` prints `<digest>  <name>` — two spaces and a name —
and the templates compare against `cut -d" " -f1`. Paste the full line and you seal a value that can
never match, reported as a mismatch. (On macOS: `shasum -a 256`, which the templates also accept.)

Put the digest in `darnlink-gate.json` next to `ref`. The shipped examples then compare it
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
