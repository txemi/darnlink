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

- `--exclude NAME` — skip any directory named `NAME` (repeatable).
- `--ignore-block NAME` — leave links inside generated blocks
  `<!-- NAME-start --> … <!-- NAME-end -->` untouched (repeatable).
- `--no-create-frontmatter-for GLOB` — for files a pipeline regenerates (e.g. `content.md`, a
  generated `INDEX.md`): never seed a uuid there (it would be wiped on the next refresh), so the
  link is left plain.

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
    rev: v0.1.0
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
