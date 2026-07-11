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

A file can remove itself from the darnlink graph entirely with a marker comment:

```markdown
<!-- darnlink-ignore-file -->
```

A file carrying this marker (anywhere, outside a code span) is **never** scanned as a source (its
links are left untouched) and **never** indexed as a target (its `uuid` does not resolve links).
This is the self-contained way to protect a generated file (e.g. an auto-built `INDEX.md`) that
lives in a directory darnlink otherwise processes — the generator just emits the marker, and no
external ignore list is needed. The marker is invisible when rendered, and (per §4) an occurrence
inside a code block is treated as an example, not as opting the file out.

## 6. Properties

- **No database, no index file, no app lock-in.** Everything needed is in the files themselves.
- **Degrades gracefully**: even a "broken" robust link is still a valid, clickable Markdown link.
- **Deterministic & idempotent**: same tree → same result; running twice changes nothing.

## 7. Relationship to prior art

This is, in spirit, "what emacs `org-id` does for org-mode, but for plain Markdown and without a
central location database": the identity travels *inside* the link and the target, so any tool can
reconcile them, in any editor, with no shared state.
