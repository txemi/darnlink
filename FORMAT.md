---
uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef
---

# The darnlink robust-link format

A tiny, plain-text convention for **self-healing Markdown links**. It is independent of the
`darnlink` tool: any program (or a human) can read and write it. This document IS the spec.

## 1. The robust link

A robust link is an ordinary Markdown link immediately followed by a UUID HTML comment:

```markdown
[link text](relative/path.md) <!-- uuid: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx -->
```

- The `[text](path)` part is a normal, clickable Markdown link. It renders and works everywhere.
- The `<!-- uuid: … -->` is an HTML comment: **invisible** in rendered output, but machine-readable.
- The UUID is the **stable identity** of the target, independent of its path.

## 2. The anchor (target frontmatter)

The target file declares the same UUID in its YAML frontmatter:

```markdown
---
uuid: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
---
# Target document
```

A UUID identifies exactly one file. (Duplicates are an error; tools must report, not guess.)

## 3. Grammar

```
robust-link := "[" text "](" path ")" ws* "<!--" ws* "uuid:" ws* UUID ws* "-->"
UUID        := 36 chars matching [0-9a-fA-F-] (canonically 8-4-4-4-12 lowercase hex)
```

- **Detection is tolerant**: any whitespace (including a newline) is allowed between `)` and the
  comment.
- **Emission is canonical**: a single space — `[text](path) <!-- uuid: <uuid> -->`.
- `path` may include a `#fragment`; it is preserved across rewrites.

## 4. Semantics & operations

- **Resolve**: the link's target is the file whose frontmatter `uuid` equals the link's UUID
  (exact match — no fuzzy/heuristic resolution).
- **Repair**: if the written `path` does not resolve to that file (the file moved), rewrite `path`
  to the correct location **relative to the file containing the link**. Text, fragment and UUID are
  preserved.
- **Robustify**: a plain link `[text](path.md)` is upgraded by ensuring the target has a `uuid`
  (creating one only because a link now references it) and appending the comment.

Scope: relative links to local `.md` files. URLs, non-`.md` targets and bare `#anchors` are ignored.
Links inside **code** — fenced blocks (```` ``` ````/`~~~`) or inline code (`` ` ``) — are also
ignored: they are examples, not navigational links, and rewriting them would corrupt the docs.

## 5. Opting a file out

Everything darnlink reads lives **in the file** — no database, no config (Principle III). Beyond the
link anchor (§1) and frontmatter `uuid` (§2), a file has three ways to tell darnlink to leave some or
all of its links alone:

| In the file | Means |
|---|---|
| `<!-- NAME-start --> … <!-- NAME-end -->` | Leave the links in this **region** alone (opt-in via `--ignore-block NAME`). |
| `<!-- darnlink-ignore-links -->` | Leave **my** links alone — but keep anchoring to me. |
| `<!-- darnlink-ignore-file -->` | Pretend I don't exist (neither source nor target). |

The two `ignore-*` markers are the two independent axes darnlink cares about — *do you rewrite my
links?* and *may others anchor to me?*:

| Marker | Its own links rewritten? | Still a target (its `uuid` resolves)? |
|---|---|---|
| *(none — default)* | yes | yes |
| `<!-- darnlink-ignore-links -->` | **no** | **yes** |
| `<!-- darnlink-ignore-file -->` | **no** | **no** |

All three are invisible when rendered, and (per §4) an occurrence inside a code block is treated as
an example, not as an opt-out.

### Generated regions — `<!-- NAME-start --> … <!-- NAME-end -->`

Links inside such a region are left untouched, exactly as if they were code. Unlike the two markers
below, the region is **opt-in from the command line**: darnlink only honours the names it is told
about (`--ignore-block NAME`, repeatable), because `NAME` is yours to choose:

```markdown
<!-- autogrid-start -->
| Doc | Path |
| A   | [a.md](docs/a.md) |
<!-- autogrid-end -->
```

Use it when a generator owns **part** of a file a human owns the rest of. If the generator owns the
**whole** file, `<!-- darnlink-ignore-links -->` says so with no CLI flag at all.

### `<!-- darnlink-ignore-links -->` — leave my links alone

```markdown
<!-- darnlink-ignore-links -->
```

darnlink never rewrites the links **inside** this file: they are not robustified, and not repaired
even when their target moves. The file stays a first-class **target**, so other documents can anchor
to it and their links keep healing when it moves.

This is what a **generated** file wants. Its generator rewrites it wholesale on every run, so any
anchoring darnlink does there is churn — but a generated index (`INDEX.md`, `PRIORITIES.md`) is
usually the file everything else links *to*, so it cannot afford to stop being a target. Stale links
inside it are not darnlink's problem to fix: the generator re-emits the correct paths on its next run.

> **Placement matters.** Put the marker **after** the frontmatter block, never before it. Frontmatter
> is only recognised at the very top of the file (§2), so a marker on line 1 pushes `---` down and
> hides the file's own `uuid` — silently costing it the target axis, which is the whole point of this
> marker. Detection itself is position-free; this ordering comes from the frontmatter format.

### `<!-- darnlink-ignore-file -->` — pretend I don't exist

```markdown
<!-- darnlink-ignore-file -->
```

A file carrying this marker (anywhere, outside a code span) is **never** scanned as a source (its
links are left untouched) and **never** indexed as a target (its `uuid` does not resolve links). Use
it for a file that should leave the graph completely — not merely for a generated one, which almost
always still wants inbound links (use `ignore-links` for that).

If a file carries both markers, `ignore-file` wins: the stronger claim takes precedence.

## 6. Properties

- **No database, no index file, no app lock-in.** Everything needed is in the files themselves.
- **Degrades gracefully**: even a "broken" robust link is still a valid, clickable Markdown link.
- **Deterministic & idempotent**: same tree → same result; running twice changes nothing.

## 7. Relationship to prior art

This is, in spirit, "what emacs `org-id` does for org-mode, but for plain Markdown and without a
central location database": the identity travels *inside* the link and the target, so any tool can
reconcile them, in any editor, with no shared state.
