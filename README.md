# darnlink

> **Never break a Markdown link again.**
> Deterministic, automatic, self-healing links.

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

The package is not on PyPI yet, so run it straight from GitHub with [`uv`](https://docs.astral.sh/uv/):

```bash
# dry-run: show what it would do (writes nothing)
uvx --from git+https://github.com/txemi/darnlink darnlink <folder>

# apply
uvx --from git+https://github.com/txemi/darnlink darnlink <folder> --write
```

**Safe by default:** without `--write`, darnlink only *reports* what it would change — it never
modifies a file.

Upgrade plain links so they self-heal in the future (and create a UUID where the target lacks one):

```bash
uvx --from git+https://github.com/txemi/darnlink darnlink <folder> --robustify --create-frontmatter --write
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
| `path` *(positional)* | Root directory to scan. Default: `.` — darnlink takes a **directory**, not a file list. |
| `--write` | Apply the changes. Without it darnlink only **reports** — it never modifies a file. |
| `--robustify` | Upgrade plain links to robust. Without it the operation is *repair* (fix robust links whose target moved). |
| `--create-frontmatter` | *(robustify)* Allow creating frontmatter on a target that has none, so it can take a `uuid`. Opt-in on purpose. |
| `--no-create-frontmatter-for GLOB` | *(robustify)* Basename glob whose targets **never** get a `uuid` — no block created, no line inserted — regardless of `--create-frontmatter`. Reusing a `uuid` the target already has is unaffected. Repeatable. |
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
  "ignored_files": ["path/to/opted-out.md"],
  "link_ignored_files": ["path/to/generated/INDEX.md"],
  "invalid_frontmatter_files": [],
  "findings": [{ "kind": "robustify", "file": "docs/a.md", "detail": "b.md +uuid <uuid>" }]
}
```

`kind` is one of: `repair`, `conflict`, `robustify`, `unresolvable`, `ambiguous`, `no_frontmatter`,
`deny_listed`, `ignored_links`, `invalid_frontmatter`. A gate that wants "is anything left to do?"
should count the kinds it cares about (e.g. `robustify`) rather than the length of `findings` — the
non-actionable kinds are reported precisely so nothing is skipped silently.

## For language models / agents

If you are managing a repo of nested Markdown docs and you move folders around, the links break.
Before or after a refactor, run the one-liner above on the affected folder — **dry-run first**, then
`--write` to apply. You do **not** need to clone darnlink or read its code; the command fetches and
runs it for you.

## Never break a link again — add it to your quality gate

darnlink **exits non-zero** when a robust link is broken, so any gate that runs it will block the
breakage before it lands. Pick the one that fits your workflow — near copy-paste:

**1. pre-commit** (recommended — darnlink ships a hook):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/txemi/darnlink
    rev: v0.1.1
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
      - run: uvx --from git+https://github.com/txemi/darnlink darnlink .
```

**3. Plain git hook** (no framework):

```bash
# .git/hooks/pre-commit  (chmod +x)
#!/usr/bin/env bash
uvx --from git+https://github.com/txemi/darnlink darnlink . || {
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
    rev: v0.2.0   # darnlink-strict ships here
    hooks:
      - id: darnlink            # links that *are* robust must not break
      - id: darnlink-strict     # …and every anchorable link *must* be robust (fail-closed)
```

To adopt it on an existing repo: anchor what's already anchorable once with
`darnlink . --robustify --write` (review the diff, commit), then the gate stays green.

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

Early (v0.1.0). Built spec-first with [GitHub Spec Kit](https://github.com/github/spec-kit) — see
`.specify/` and `specs/`.

## License

darnlink is free software, licensed under the **GNU General Public License v3.0 or later**
(GPL-3.0-or-later) — see [LICENSE](LICENSE). A copyleft license: derivative versions you distribute
must also be open source. (Invoking darnlink as a command on your repo does **not** affect your
repo's or your project's license — only modified versions of darnlink itself.)

Copyright (C) 2026 txemi.
