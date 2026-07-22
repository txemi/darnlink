# darnlink

> **Never break a Markdown link again.**
> Deterministic, automatic, self-healing links.

[![PyPI](https://img.shields.io/pypi/v/darnlink.svg)](https://pypi.org/project/darnlink/)
[![CI](https://github.com/txemi/darnlink/actions/workflows/ci.yml/badge.svg)](https://github.com/txemi/darnlink/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

Markdown is excellent for documentation: it gives you fine-grained version history of how a
document evolves, and it is easy for both humans and language models to read and process. It has
one flaw — **links break the moment you refactor.** Move a folder, rename a file, and every link
pointing into it dies.

`darnlink` fixes that flaw **deterministically and automatically**. Run it after (or before) any
reorganisation and it heals the links. It is built for trees of **many nested Markdown files**
that get relocated and refactored over time.

> ### 🌐 Cross-repo web links (experimental, opt-in)
>
> Beyond local links, darnlink can also anchor and verify **cross-repo web links** — a Markdown link
> to a `https://github.com/owner/repo/blob/…` file in *another* repository, anchored to that file's
> `uuid`. The opt-in **`web-check --online`** command (off by default; tokenless for public
> destinations) anchors a plain link and verifies an anchored one, failing on drift. It's
> **experimental**, and the core stays fully offline unless you invoke it. See
> [Elevating your link gate §8](docs/elevating-your-link-gate.md) <!-- uuid: e95eaed1-9866-4c48-a0d7-99a6382f5bf9 -->.

## See it heal a link

![darnlink repairs a link whose target was moved — same uuid, new path](demo/demo.gif)

A robust link carries its target's uuid inline and stays a normal, clickable Markdown link. Move the
target and the path goes stale; `darnlink . --write` finds it by uuid and rewrites **only** the path:

```diff
-See the [design doc](docs/design.md) <!-- uuid: 7f3a1e2c -->
+See the [design doc](architecture/design.md) <!-- uuid: 7f3a1e2c -->
```

That's the whole idea: the link survived the move on its own.

## Use it in one line — no install, no clone

darnlink is on [PyPI](https://pypi.org/project/darnlink/), so [`uv`](https://docs.astral.sh/uv/)
fetches and runs it for you — nothing to install:

```bash
# dry-run: show what it would do (writes nothing)
uvx darnlink <folder>

# apply
uvx darnlink <folder> --write
```

Prefer a permanent install? `pipx install darnlink` (or `uv tool install darnlink`), then just
`darnlink <folder>`.

**Straight from the repo** — when you need a ref PyPI can't give you: an *immutable commit* for a
reproducible CI gate (a tag can be force-moved; a SHA can't), or unreleased `main`:

```bash
uvx --from git+https://github.com/txemi/darnlink@v0.7.0 darnlink <folder>   # a tag
uvx --from git+https://github.com/txemi/darnlink@<sha>  darnlink <folder>   # an immutable commit
uvx --from git+https://github.com/txemi/darnlink        darnlink <folder>   # latest main
```

**Safe by default:** without `--write`, darnlink only *reports* what it would change — it never
modifies a file.

Upgrade plain links so they self-heal in the future (and create a UUID where the target lacks one):

```bash
uvx darnlink <folder> --robustify --create-frontmatter --write
```

## How it works (it's simple)

Point it at a documentation folder; it scans the links and does two things:

- **Correct links → protected for the future.** It writes a `uuid` into the **target's**
  frontmatter, and adds an **invisible HTML comment** carrying that same uuid next to the link at
  the **source**. The link is now anchored to the file's *identity*, not to its path.
- **Already-protected links that broke** (the target was moved or renamed) → **repaired**: darnlink
  finds the target by its uuid and rewrites the path.

Every pass protects the correct links and repairs the broken-but-protected ones. It is
**deterministic** (exact UUID match — no heuristics, no network), **idempotent**, and needs **no
database and no index file**: a repo that uses darnlink links still works with darnlink uninstalled.

A robust link stays a normal, clickable Markdown link:

```markdown
See [the design doc](docs/design.md) <!-- uuid: 7f3a1e2c-... -->
```

Links to **directories** work too: a link to `docs/guide/` is anchored to the uuid of that folder's
`README.md`, so it heals when the folder moves — same guarantee, for the hubs you link to by folder.
If a linked folder has no `README.md`, `--create-readme` makes one (with a uuid) so the link can be
anchored; it is opt-in and only ever creates a README inside a directory that already exists.

Format spec: [FORMAT.md](FORMAT.md) <!-- uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef -->.

## Excluding parts of the tree

darnlink walks the **whole** folder by default. Skip the parts that must not be touched — vendored
or submodule content, mirrors, generated output:

```bash
darnlink <folder> --exclude vendor --exclude mirror --ignore-block autogrid
```

`--exclude` and `--ignore-block` are repeatable. `--exclude` is a glob — **keep patterns tight**: a
wide one like `*` silently drops directories from the scan (their links stop being checked). Prefer
word-boundary patterns (`old`, `old_*`, `*_old`) over a greedy `*old*`. For a whole file rather than a
directory or a region, a file can opt itself out from the inside — see [FORMAT.md §5](FORMAT.md#5-opting-a-file-out) <!-- uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef -->.
The full flag list is under [All options](#all-options) below.

## All options

The sections above introduce these in context; this is the full list (same as `darnlink --help`).

| Option | What it does |
|---|---|
| `path` *(positional)* | Root directory to scan. Default: `.` — darnlink takes a **directory**, not a file list. (To write to specific files while still scanning the whole tree, use `--only`, below.) |
| `--write` | Apply the changes. Without it darnlink only **reports** — it never modifies a file. |
| `--robustify` | Upgrade plain links to robust. Without it the operation is *repair* (fix robust links whose target moved). |
| `--create-frontmatter` | *(robustify)* Allow creating frontmatter on a target that has none, so it can take a `uuid`. Opt-in on purpose. |
| `--no-create-frontmatter-for GLOB` | *(robustify)* Basename glob whose targets **never** get a `uuid` — no block created, no line inserted — regardless of `--create-frontmatter`. Reusing a `uuid` the target already has is unaffected. Repeatable. |
| `--only FILE` | Restrict **writes** to these `.md` files. The tree is still scanned and indexed in full — so a link's target can live anywhere — but only these files are modified. Repeatable. See [Scoping writes to specific files](#scoping-writes-to-specific-files---only). |
| `--only-from FILE` | Read `--only` paths from `FILE`, one per line (`-` = stdin). Combines with `--only`. Lets you pipe a generated list (e.g. staged files) without darnlink knowing about git. |
| `--no-target-writes` | *(with `--only`)* Never write a `uuid` into a target **outside** the write scope: such links are left plain and reported. Guarantees **no** file outside `--only` is touched. |
| `--exclude PATTERN` | Skip any directory whose name matches `PATTERN` (glob / `fnmatch`, case-sensitive; a plain name matches exactly). Repeatable — e.g. `--exclude old --exclude 'old_*' --exclude '*_old'` skips the whole `old` family. |
| `--ignore-block NAME` | Leave links inside `<!-- NAME-start --> … <!-- NAME-end -->` blocks alone. Repeatable. |
| `--json` | Machine-readable output (see below). |

Files can also opt themselves out from the inside, with no CLI flag: see
[FORMAT.md §5](FORMAT.md#5-opting-a-file-out) <!-- uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef --> for `<!-- darnlink-ignore-links -->` (leave *my* links
alone, but keep anchoring to me) and `<!-- darnlink-ignore-file -->` (drop me from the graph).

### `--json` output

Stable shape, meant for gates and scripts:

```json
{
  "wrote": 0,
  "applied": false,
  "write_scope": null,
  "suppressed_outside_write_scope": 0,
  "ignored_files": ["path/to/opted-out.md"],
  "link_ignored_files": ["path/to/generated/INDEX.md"],
  "invalid_frontmatter_files": [],
  "findings": [{ "kind": "robustify", "file": "docs/a.md", "detail": "b.md +uuid <uuid>" }]
}
```

`kind` is one of: `repair`, `conflict`, `robustify`, `unresolvable`, `ambiguous`, `no_frontmatter`,
`out_of_scope`, `deny_listed`, `ignored_links`, `invalid_frontmatter`, `target_uuid_write`,
`target_write_refused`. A gate that wants "is anything left to do?" should count the kinds it cares
about (e.g. `robustify`) rather than the length of `findings` — the non-actionable kinds are
reported precisely so nothing is skipped silently.

`write_scope` is `null` unless `--only` is in effect, when it lists the files that may be written;
`suppressed_outside_write_scope` counts actionable findings in files outside that scope — not shown,
but surfaced so a narrowed run never reads as a clean tree.

`out_of_scope` is worth calling out: it means a plain link's target **exists but was never scanned**
(it lives outside `path`, or an `--exclude` skipped it), so its `uuid` is unknown and the link is
left plain. That is a different fact from `no_frontmatter` (target scanned, but it has none) — the
two used to collapse into one, which reported a scope miss as if the target were malformed.

### Scoping writes to specific files (`--only`)

By default darnlink writes to every file it scans. `--only` narrows the **write** scope to named
files while still building the target graph from the whole tree — the two are separate axes:

```bash
# Scan the whole repo (so targets resolve wherever they live), but only rewrite ONE file:
darnlink . --robustify --write --only tasks/56/README.md
```

Why the split matters: the link you want to anchor lives in your file, but its **target** usually
lives elsewhere in the repo. Scanning only your subtree (`darnlink tasks/56`) can't see the target,
so it reports `out_of_scope` and anchors nothing; scanning the whole repo without `--only` would
rewrite every robustifiable link in the tree, including other people's work in flight. `--only` is
"read everything, write here".

- The **one** write that may land outside `--only` is adding a `uuid` to a *target* so the link can
  be anchored at all — it is reported (kind `target_uuid_write`) before it happens. Pass
  `--no-target-writes` to refuse even that: the link stays plain, and **nothing** outside `--only`
  is touched.
- A **repair** run under `--only` only ever inspects the links *inside* the scoped files. A moved
  target's *inbound* links live in files you didn't name — a clean scoped result is **not** proof the
  tree is clean. Keep a full-tree run in CI for that.
- darnlink never touches git. To scope to your staged files, pipe them in — this is the whole
  `--only-from -` use case:

```bash
git diff --cached --diff-filter=ACMR --name-only -- '*.md' \
  | darnlink . --robustify --write --only-from -
```

  (darnlink edits the files but does **not** re-stage them; your hook re-runs `git add` if it wants
  the fixes in the same commit.)

## For language models / agents

If you are managing a repo of nested Markdown docs and you move folders around, the links break.
Before or after a refactor, run the one-liner above on the affected folder — **dry-run first**, then
`--write` to apply. You do **not** need to clone darnlink or read its code; the command fetches and
runs it for you.

## Never break a link again — add it to your quality gate

darnlink **exits non-zero** when a robust link is broken, so any gate that runs it will block the
breakage before it lands. Pick the one that fits your workflow — near copy-paste:

> **Want a ready-made wrapper instead of wiring it yourself?** [`recipes/darnlink-gate`](recipes/README.md)
> does all of the below (both checks, staged-in-pre-commit vs whole-repo-in-CI, pinned ref, fail-open)
> from a tiny `darnlink-gate.json`. It's a reference recipe, fetchable in CI without a token — with
> complete copy-paste hook & CI files in [`recipes/examples/`](recipes/examples/).

**1. pre-commit** (recommended — darnlink ships a hook):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/txemi/darnlink
    rev: v0.7.0
    hooks:
      - id: darnlink            # fail the commit if any robust link is broken
      # - id: darnlink-repair   # …or auto-repair in place instead of failing
```

**2. GitHub Actions** (gate every push & PR):

```yaml
# .github/workflows/darnlink.yml
name: darnlink
on: [push, pull_request]
jobs:
  links:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uvx darnlink .
```

**3. Plain git hook** (no framework):

```bash
# .git/hooks/pre-commit  (chmod +x)
#!/usr/bin/env bash
uvx darnlink . || {
  echo "darnlink: broken robust links — re-run with --write to repair"; exit 1
}
```

> The three run the same check (`darnlink <folder>`, dry-run): they **report** breakage and fail.
> To have the gate **fix** links instead of just failing, use `--write` (Actions/hook) or the
> `darnlink-repair` hook id (pre-commit).

### Stricter: require every link to be *robust* (fail-closed)

The gate above keeps the robust links you already have from breaking. It says nothing about **plain**
relative links that were never anchored — so a fresh, un-anchored link sails through, and the next
refactor silently breaks it. To close that gap, run the **robustify check** (dry-run — it reports,
it does **not** write):

```bash
darnlink . --robustify        # exits non-zero if any plain link to an anchorable target is un-anchored
```

> **One command for both axes — `darnlink check`.** `--robustify` and plain `darnlink .` catch
> *disjoint* failures (an un-anchored plain link vs. a broken robust link) — a gate that runs only one
> is blind to the other. `darnlink check` runs **both** in one report-only invocation and exits with a
> distinguishable code — `0` clean · `2` integrity (broken/invalid) · `3` strict (un-anchored) — so CI
> can't forget a half and can tell *which* axis failed. darnlink checks; your CI/hook decides to block.

This is **fail-closed**: it fails until every link that *can* be robust *is* robust. A target is
*anchorable* when it's a local Markdown file with frontmatter (darnlink reuses its `uuid`, or adds
one). Links whose target **can't** take a `uuid` are left alone — external/non-local targets,
deny-listed targets, and targets **without frontmatter** (unless you opt in with
`--create-frontmatter`). So it only demands robustness where robustness is possible. Wire it as a
pre-commit hook with the `darnlink-strict` id:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/txemi/darnlink
    rev: v0.7.0   # darnlink-strict ships since v0.2.0
    hooks:
      - id: darnlink            # links that *are* robust must not break
      - id: darnlink-strict     # …and every anchorable link *must* be robust (fail-closed)
```

To adopt it on an existing repo: anchor what's already anchorable once with
`darnlink . --robustify --write` (review the diff, commit), then the gate stays green.

> **📘 Going all the way — elevate a whole repo to fail-closed.** The strictest setting
> (`--robustify --create-frontmatter`: *every link's target must carry a `uuid`*) is reachable even
> on a large repo with a big generated mirror. The end-to-end playbook — the two-bucket strategy,
> how generators cooperate (stable `uuid` + the `darnlink-ignore-links` marker), bulk-adopting a mirror from
> its stored raw, the traps, and the pre-commit/pre-push/CI wall architecture — is in
> **[docs/elevating-your-link-gate.md](docs/elevating-your-link-gate.md) <!-- uuid: e95eaed1-9866-4c48-a0d7-99a6382f5bf9 -->**.

> **Scope note for repos with many contributors.** All the hooks run over the **whole tree**
> (`pass_filenames: false` — darnlink takes a directory, not a file list), and the strict check is
> *fail-closed*. So a plain, un-anchored link that **someone else** left in a file you never touched
> will block **your** commit. That is fine for a small repo, but with several people (or parallel
> agents) committing at once it means one un-anchored link blocks everyone. A practical split: run
> `darnlink-strict` in **CI** (the real wall — nothing un-anchored lands on the main branch), and the
> plain `darnlink` hook **locally** (fast, and it only fails on links that actually broke), so a
> teammate's in-flight plain link doesn't stop your commit.

**Generated files** with plain links you don't want to anchor: have the generator emit
`<!-- darnlink-ignore-links -->` (just below the frontmatter). darnlink then leaves the links inside
them alone — no churn when the generator re-runs — while they stay linkable targets, which matters
because a generated `INDEX.md` is usually what everything else links *to*. Use
`<!-- darnlink-ignore-file -->` only for a file that should leave the graph entirely (it also stops
resolving inbound links), or `--exclude <dir>` for a whole tree. See
[FORMAT.md §5](FORMAT.md#5-opting-a-file-out) <!-- uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef -->
for the two markers side by side. darnlink itself is gated this way (see `tools/check.sh` / CI).

## Used by

- [immich-autotag](https://github.com/txemi/immich-autotag) — a rule engine for organizing Immich photo libraries — runs darnlink as a **read-only docs-link quality gate** in pre-commit, Jenkins, and GitHub Actions, so its Markdown docs links don't break when files move.

## Prior art & how darnlink differs

The idea of surviving refactors by anchoring to an identity isn't new, but the specific combination is a gap:

- **emacs `org-id`** — the closest relative: `[[id:UUID]]` links survive moving files. But it's **org, not Markdown**, the link is *only* the id, and resolution needs a **central database** (`~/.org-id-locations`) tied to emacs.
- **Obsidian / VS Code / Front Matter CMS** — update links on rename, but **path-based** and only *inside the app*: a `git mv` or any external script breaks them. They depend on the editor.
- **markdown-link-check / dead-link-checker** — only **detect** broken links; they neither repair nor use a uuid.
- **Docusaurus / MkDocs / 11ty** — map ids→urls at *site build* time; not a repo-maintenance tool.

**darnlink's niche:** Markdown-native, **no database**, **editor-agnostic**. The link carries the human path **and** the uuid inline — `[text](path) <!-- uuid -->` — so it stays clickable and readable even when "broken", and is self-describing (uuid by the link and in the target's frontmatter). And it both **repairs** moved paths *and* **upgrades** plain links to robust ones. *"What `org-id` does for emacs, but for plain Markdown and with no database."*

## Status

Early (v0.7.0). Built spec-first with [GitHub Spec Kit](https://github.com/github/spec-kit) — see
`.specify/` and `specs/`.

## License

darnlink is free software, licensed under the **GNU General Public License v3.0 or later**
(GPL-3.0-or-later) — see [LICENSE](LICENSE). A copyleft license: derivative versions you distribute
must also be open source. (Invoking darnlink as a command on your repo does **not** affect your
repo's or your project's license — only modified versions of darnlink itself.)

Copyright (C) 2026 txemi.
