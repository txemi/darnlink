# Feature Specification: typed anchor and link, published in LinkML

**Feature Branch**: `019-typed-anchor-and-link`

**Created**: 2026-10-29

**Status**: Implemented

**Input**: `darnlink yaml-refs` (0.29.0) checks `{uuid, link}` references in YAML data, at the
positions a schema declares as `DarnlinkRef`. But darnlink never published that type: every
repository that wanted it wrote its own copy, by hand, with its own idea of what a uuid looks like.
A typed reference needs two published types, from one source, that any repository can import or
pin: the **anchor** (an element says "I am identified here") and the **link** (an element says
"that one, over there").

Supersedes the unmerged pull request #11, which hand-wrote a `ref.schema.json` with a
relative-only `link` and a case-insensitive `uuid`.

---

## The two types

| Type | Kind | Shape |
|---|---|---|
| `DarnlinkAnchor` | LinkML `type` (`typeof: string`) | canonical RFC 4122 text form, **lowercase only**: `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?!\n)$`. Any version |
| `DarnlinkRef` | LinkML `class` | object `{link, uuid}`, both required, **no other property** |

`DarnlinkRef` fields:

- `link`: where the target is. A path relative to the file that carries the reference (a
  `#fragment` after it is allowed, a directory path means its `README.md`), or an `http(s)` URL. Not
  an absolute path, not a bare `#fragment`, not another scheme, not empty or blank, no line break
  (CR or LF) anywhere. The name stays `link`: it is what `yaml-refs` already reads.
  - A relative file whose name contains a colon reads as a scheme: write it `./notes:1.md`.
  - The URL scheme is lowercase only: `HTTPS://…` is rejected.
- `uuid`: the target's anchor, range `DarnlinkAnchor`.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Source of truth | **LinkML** (`src/darnlink/schemas/v1/darnlink_types.linkml.yaml`); the JSON Schema next to it is generated and committed | LinkML consumers import the types; JSON Schema consumers pin the generated file without installing LinkML. One source, so the two cannot disagree |
| Anchor case | **lowercase only** | one canonical text per identity: a search, a diff and an exact-match index see the same string. `uuid.uuid4()` already prints lowercase |
| `link` and `uuid` as global slots or class attributes | **class attributes** | a schema that imports these types keeps its own `link` and `uuid` slots free |
| How a consumer reaches the anchor in JSON Schema | **`$defs/DarnlinkAnchor`**, added by the generation script (see below); `DarnlinkRef.uuid` is a `$ref` to it | `gen-json-schema` inlines a LinkML type and emits no `$defs` entry for it |
| Identifier | `https://github.com/txemi/darnlink/schemas/v1/darnlink_types` as LinkML `id`, prefix base and JSON Schema `$id` | an identifier, not a location: nothing resolves it over the network |

## Where an anchor lives, per kind of file

| File kind | Where its anchor is |
|---|---|
| Markdown | the frontmatter `uuid` (unchanged: [FORMAT.md](../../FORMAT.md) <!-- uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef -->) |
| YAML or JSON with a schema | any field whose schema types it as `DarnlinkAnchor`, at any depth. A file can carry several (one per element it describes) |
| Code | a `uuid` key inside a YAML block opened by `#---` in the header comments |
| Binaries (images, PDFs, archives…) | none. Link the README that describes them |

This table defines where anchors **are**. Which of those places darnlink **indexes** today is
unchanged (Markdown frontmatter, and the top-level `uuid` of a YAML file for `yaml-refs`); the rest
is out of scope below.

Both patterns are written to mean the same in ECMA-262 and in Python, which is what `jsonschema`
runs. Python's `$` also matches before a trailing newline, so the anchor ends in `(?!\n)$`. The
link forbids CR, LF, U+2028 and U+2029 with a leading lookahead, because ECMA-262's `.` stops at the
last two and Python's does not. One difference is left: the two disagree on whether a few rare
characters are whitespace (U+001C to U+001F and U+0085 are for Python, U+FEFF is for ECMA-262), so a
link that starts or ends with one of them is judged differently. No real link does.

## Versioning

- The `$id` (and the LinkML `id`) contains `/v1/`. **v1 never breaks**: a change that would reject
  data v1 accepted, or accept data v1 rejected in a way consumers rely on, goes to a new `v2/`
  directory next to it, and v1 stays published.
- Consumers **pin a copy** of the JSON Schema with its sha256, and register it under its `$id`.
  Never a live `$ref` to the network: a validator that fetches is a build that breaks offline and
  a schema that changes under you.
- The generated file depends only on the LinkML source: the generator's own `metamodel_version` is
  dropped, and keys are sorted.

## Duplicate anchors

Copying a file copies its anchor. Keeping anchors unique is the copier's responsibility; darnlink
does not rewrite either copy. A link to a duplicated anchor is reported as `ambiguous`, as it is
today for Markdown.

## Functional requirements

- **FR-001** The package ships `darnlink/schemas/v1/darnlink_types.linkml.yaml` and
  `darnlink/schemas/v1/darnlink_types.schema.json` (wheel and sdist).
- **FR-002** The JSON Schema is byte-identical to what `tools/gen_schemas.py` generates from the
  LinkML file. `tools/gen_schemas.py --check` exits 1 when it is not.
- **FR-003** `$defs/DarnlinkAnchor` and `$defs/DarnlinkRef` both exist; `DarnlinkRef.uuid` is a
  `$ref` to `#/$defs/DarnlinkAnchor`.
- **FR-004** `DarnlinkRef` rejects: a missing `link` or `uuid`, an uppercase or malformed `uuid`, a
  `uuid` with a trailing newline, an extra property, an absolute path, a bare fragment, a
  non-http(s) or uppercase scheme, an empty or blank `link`, a `link` with a CR or LF anywhere.
- **FR-005** `DarnlinkRef` accepts a relative path (with or without a fragment, file or directory)
  — a colon in a file name only behind `./` — and an `http(s)` URL.
- **FR-006** A `$ref` into a pinned copy (`…/darnlink_types.schema.json#/$defs/DarnlinkRef`) is
  recognised by `yaml-refs` as a reference position, by definition name, with no code change.

## Generation

`uv run --extra dev python tools/gen_schemas.py` runs LinkML's `JsonSchemaGenerator`, then applies
three deterministic fixes, each documented in the script: it adds `$defs/DarnlinkAnchor` from the
LinkML type and replaces the inlined copy in `DarnlinkRef.uuid` with a `$ref` (after checking the
inlined copy is exactly the type, so a generator change fails loudly); it drops
`metamodel_version`; it writes sorted keys with a trailing newline. `linkml` is a `dev` dependency
only: the runtime package does not need it.

## Out of scope (later features)

- Recognising the types by `$id` in `yaml-refs` (today it recognises `DarnlinkRef` by definition
  name or by the `ref.schema.json` file name).
- Indexing typed anchors: `DarnlinkAnchor` fields inside YAML/JSON at any depth, and `#---` blocks
  in code, as link targets.
- Filling a missing `uuid` from `link` (robustifying a `DarnlinkRef`).
- Verifying a `link` that is a URL.

## Tests

`tests/test_typed_anchor_and_link.py`: the committed JSON equals a fresh generation (skipped
without `linkml`); valid and invalid instances against a copy registered under its `$id`, never
fetched; the anchor alone; the `yaml-refs` recognition of FR-006; the files are present under the
package and inside the wheel and sdist built with `uv build`. The drift test and the
extra-property case were checked by mutation (flipping `additionalProperties` in the committed JSON
fails both), and the line-break and blank cases by running them against the first, looser patterns.
