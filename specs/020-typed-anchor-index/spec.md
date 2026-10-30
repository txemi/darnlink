# Feature Specification: typed anchors as link targets, recognised by `$id`

**Feature Branch**: `020-typed-anchor-index`

**Created**: 2026-10-29

**Status**: Draft — design agreed here, delivered in three steps (below)

**Input**: feature 019 published the two types, `DarnlinkAnchor` and `DarnlinkRef`, and said where
an anchor lives in each kind of file. darnlink still indexes only Markdown frontmatter (and the
top-level `uuid` of a YAML file for `yaml-refs`), recognises `DarnlinkRef` by name only, and
reports a reference with a `link` and no `uuid` as malformed instead of completing it. This
feature closes the three items 019 left out of scope, except verifying URLs.

---

## The problem with recognising an anchor

A position is an anchor because its schema says so, never because a value looks like a uuid: most
uuids in data are foreign keys, not identities. But a LinkML `type` is **inlined** by
`gen-json-schema`: a consumer whose slot has `range: DarnlinkAnchor` gets the pattern copied into the
property, with no `$ref` and nothing that names the type. Feature 019 fixed this only for darnlink's
own schema (its generation script adds `$defs/DarnlinkAnchor` and points `DarnlinkRef.uuid` at it).

Matching the inlined pattern is not an option: the pattern of any lowercase uuid is the same text,
so every uuid field would become an anchor.

## Decisions

| Question | Decision | Why |
|---|---|---|
| What makes a schema position an anchor | its node is a `$ref` to `DarnlinkAnchor` | the type is named, so the intent is explicit; an inlined pattern is not an anchor |
| How the `$ref` is recognised | by **`$id`**: a `$ref` whose base is `https://github.com/txemi/darnlink/schemas/v<N>/darnlink_types` and whose fragment is `/$defs/DarnlinkAnchor`; or a `$ref` to a local file whose own `$id` is that one; or a same-document `#/$defs/DarnlinkAnchor` | the `$id` is the identity of the published type; a pinned copy is registered under it (019), so the three spellings name the same thing |
| Same rule for `DarnlinkRef` | yes, added to the name match `yaml-refs` has today, which stays | old schemas keep working; the `$id` form no longer depends on a definition name that anyone could reuse |
| Who emits the `$ref` in a consumer schema | the consumer's generation step, as darnlink's own `tools/gen_schemas.py` does | darnlink reads schemas, it does not rewrite them. A consumer that inlines gets no anchors indexed, and the `check` summary says so |
| Several anchors in one file | allowed (one per element). A link to such a file names the element with a JSON Pointer fragment: `data.yaml#/hosts/3` | a path alone cannot say which element; the pointer is what `yaml-refs` already prints |
| Anchor in code | a `uuid` key in a YAML block between two `#---` lines, among the leading `#` comments of the file | one comment syntax in this step (`#`: Python, shell, YAML, TOML, Ruby…); others are a later feature |
| Filling a missing `uuid` | `yaml-refs --write` writes it when the `link` resolves to a target with **exactly one** candidate anchor (the file's, or the element the pointer names) | the link is the only evidence; with zero or several candidates darnlink reports and writes nothing. It never mints a uuid for a non-Markdown target |
| Duplicates | as in 019: reported `ambiguous`, never rewritten | unchanged |

## Delivery, in three steps (one pull request each)

1. **Recognition by `$id`, and anchors in YAML** (`yaml-refs`) — *implemented*: `DarnlinkRef` and
   `DarnlinkAnchor` positions recognised by `$id`, pinned copy or local definition; the anchors of
   every YAML file with a local schema, at any depth, become `yaml-refs` targets, and a fragment that
   is a JSON Pointer is repaired with the path when the element moved.
2. **The rest of the index**: JSON files (by their `$schema` key) and code files (their `#---`
   block) as targets too, and Markdown links (`<!-- uuid: … -->`) resolving against the whole index.
3. **Filling the `uuid` from the `link`**: `yaml-refs` reports `fillable` instead of `malformed` for
   a reference with a `link` and no `uuid` whose target has exactly one candidate, and `--write`
   inserts the line, byte-preserving like today's link repairs.

## Functional requirements

- **FR-001** A `$ref` equal to `https://github.com/txemi/darnlink/schemas/v1/darnlink_types#/$defs/DarnlinkAnchor`
  (any `/v<N>/`), to a local file whose `$id` is that base with fragment `/$defs/DarnlinkAnchor`, or
  to `#/$defs/DarnlinkAnchor` marks an anchor position. The same three forms with `DarnlinkRef` mark
  a reference position; the current name match is kept.
- **FR-002** A property whose schema only repeats the anchor's pattern is **not** an anchor position.
- **FR-003** The index holds, per anchor: the file, the JSON Pointer of the element that carries it
  (empty for a file-level anchor: Markdown frontmatter, a top-level YAML `uuid`, a code `#---`
  block), and the value.
- **FR-004** An anchor value that is not a lowercase canonical uuid, or an anchor that is an item of
  a list instead of a key of the element it identifies, is reported `invalid-anchor` and is not a
  target (not even through the plain top-level `uuid`), as for Markdown frontmatter today.
- **FR-005** A reference to an element's anchor carries that element's pointer as the fragment of
  its `link`; with the `uuid` present, a missing or stale fragment is repaired like a stale path.
  Without a `uuid` (step 3), a link to a file with several anchors and no fragment is `ambiguous`.
- **FR-006** `yaml-refs --write` fills a missing `uuid` only with exactly one candidate, never for a
  web link, and re-reads the file to check that only that line was added.
- **FR-007** Excludes, the ignore-file marker and the out-of-root rules apply to the new target
  files exactly as to Markdown.

## Known limits (step 1)

- `--write` rewrites a `link:` line only when every occurrence of its text in the file is being
  repaired to the same new text (the rule `yaml-refs` already had). Several bare `link: hosts.yaml`
  lines that need different fragments are reported and left to the reader.
- A draft-07 `#/definitions/DarnlinkAnchor` is not recognised: the published schema uses `$defs`.

## Out of scope (later features)

- Comment syntaxes other than `#` for code anchors (`//`, `--`, `/* */`).
- Rewriting consumer schemas (emitting the `$ref`): a consumer's own generation step.
- Verifying a `link` that is a URL.

## Tests

One test module per step. Step 1: each of the three `$ref` forms, for both types, positive and
negative (an inlined pattern; a `DarnlinkAnchor` definition in a local file under another `$id`;
the name match for `DarnlinkRef` still accepted). Step 2: anchors at depth
in YAML and JSON, a code `#---` block, several anchors with and without a pointer fragment,
duplicates, an invalid value, excludes. Step 3: fill with one candidate, refuse with zero or several
and for a web link, byte-identical output except the added line.
