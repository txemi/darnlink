"""Typed references in YAML data files: `darnlink yaml-refs` (EXPERIMENTAL).

A reference from structured data to another document of the repository has the same two halves as a
robust Markdown link: `{uuid, link}`. `link` is the path a reader follows, relative to the YAML file
that carries it; `uuid` is the identity of the target, the part that survives a move. That shape is
the `DarnlinkRef` type.

darnlink does not guess which values are references from their shape: a mapping that happens to have
a `uuid` and a `link` key is not enough. A YAML file declares its JSON Schema with the usual modeline
(`# yaml-language-server: $schema=<path>`), and only the positions whose schema node is a `$ref` to
the reference type are checked. The type is recognised by name, so both ways of declaring it work:

- a `$ref` to a local definition called `DarnlinkRef` (`#/$defs/DarnlinkRef`), as LinkML generates
  when a schema imports the type;
- a `$ref` to the published schema of the type (a path or URL ending in `ref.schema.json`).

A `$ref` to the published `$id` (`https://github.com/txemi/darnlink/schemas/v1/darnlink_types#/$defs/DarnlinkRef`)
is one of the first kind. The anchor type, `DarnlinkAnchor`, is recognised only by that identity (feature 020): the
`$id`, a local file whose own `$id` is that one (a pinned copy), or `#/$defs/DarnlinkAnchor` in the same document.

The targets are the frontmatter `uuid` of every `.md` file (the same index as the Markdown links), the
top-level `uuid` of every YAML file, every typed anchor of a YAML file with a local schema, at any depth, and
(step 2, `darnlink.typed_anchors`) the typed anchors of JSON files and the `#---` blocks of code files.
An anchor that identifies one element of a file (`/hosts/3/uuid` identifies `/hosts/3`) is reached with that
element's JSON Pointer as the fragment of the link (`hosts.yaml#/hosts/3`), and the fragment is repaired like
the path. An anchor that is not a lowercase canonical uuid is reported `invalid-anchor`.
Each reference is then judged like a robust Markdown link:
correct, repairable (the uuid lives elsewhere: the new relative path is proposed, and written with
`--write`), conflicting (the path still names an existing file that is not the uuid's), unresolvable
or ambiguous. A `link` that is a web URL is not checked here (a `DarnlinkWebRef` may point to
another repository).

A reference with a `link` and no `uuid` key (step 3) is `fillable` when the link names a file with exactly one
candidate anchor: the element its JSON Pointer fragment names or, without one, the file's own anchor (and, when the
file has none, its only element anchor). `--write` inserts the `uuid:` line under the `link:` line and keeps every
other byte. With zero candidates it stays `malformed`, with several it is `ambiguous`, and a web link is never
filled: darnlink never mints a uuid, it copies the one the target already declares.

Known limits: a `$ref` to another file (other than the reference type itself), `prefixItems`, `if` and
`not` are not followed, and a repeated `link` key is not reported (the YAML loader keeps the last one).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import unquote

from .frontmatter_index import DEFAULT_EXCLUDES, build_index, dir_excluded
from .paths import is_web_href, relative_link, resolve_href, resolved, split_fragment

REF_DEF_NAME = "DarnlinkRef"
ANCHOR_DEF_NAME = "DarnlinkAnchor"
REF_SCHEMA_FILE = "ref.schema.json"
YAML_SUFFIXES = (".yaml", ".yml")
MAX_DEPTH = 64

#: The `$id` of the published types (feature 019), any major version. An identifier, never fetched.
TYPES_ID = re.compile(r"https://github\.com/txemi/darnlink/schemas/v[0-9]+/darnlink_types")
#: An anchor value: canonical RFC 4122 text, lowercase only (the `DarnlinkAnchor` type), used with `fullmatch`.
CANONICAL_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

REF, ANCHOR = "ref", "anchor"

_MODELINE = re.compile(r"^#\s*yaml-language-server:\s*\$schema=(\S+)")

OK, REPAIR, CONFLICT, UNRESOLVABLE, AMBIGUOUS, MALFORMED, NO_SCHEMA, UNREADABLE, INVALID_ANCHOR, FILLABLE = (
    "ok", "repair", "conflict", "unresolvable", "ambiguous", "malformed", "unreadable-schema", "unreadable-yaml",
    "invalid-anchor", "fillable")

#: What `_load_yaml` returns for a file it cannot read. Not None: an empty file loads as None and is readable.
UNREADABLE_DOC = object()


@dataclass(frozen=True)
class RefFinding:
    """One reference that is not correct. `pointer` is a JSON Pointer into the YAML document."""
    kind: str
    file: str
    pointer: str
    link: str
    uuid: str
    detail: str
    new_link: str = ""


def iter_yaml_files(root: Path, excludes: set[str] = DEFAULT_EXCLUDES) -> Iterator[Path]:
    """Every `.yaml`/`.yml` file under `root`, skipping excluded directory names (same rule as `.md`)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not dir_excluded(d, excludes))
        for name in sorted(filenames):
            if name.endswith(YAML_SUFFIXES):
                yield Path(dirpath) / name


def _load_yaml(path: Path):
    """The parsed document, or UNREADABLE_DOC if it cannot be read. Any error counts as unreadable: PyYAML raises more
    than YAMLError on valid syntax with an impossible value (a date such as 2023-13-45 is a ValueError), and
    one such file anywhere in the tree must not abort the whole run."""
    import yaml
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    try:
        return yaml.load(path.read_text(encoding="utf-8-sig"), Loader=loader)
    except Exception:
        return UNREADABLE_DOC


def modeline_schema(path: Path) -> Optional[str]:
    """The `$schema=` of the yaml-language-server modeline in the leading comment lines, if any. A `---`
    document marker on the first line is allowed before them."""
    try:
        # errors="replace": a file that is not UTF-8 still shows its modeline, and is then reported as unreadable
        with path.open(encoding="utf-8-sig", errors="replace") as fh:
            for n, line in enumerate(fh):
                if n == 0 and line.rstrip("\r\n") == "---":
                    continue
                if not line.startswith("#"):
                    break
                m = _MODELINE.match(line)
                if m:
                    return m.group(1)
    except (OSError, UnicodeDecodeError):
        return None
    return None


def is_ref_type(ref: object) -> bool:
    """True if a `$ref` names the reference type, by definition name or by its published schema file."""
    if not isinstance(ref, str):
        return False
    tail = ref.rstrip("/").rsplit("/", 1)[-1]
    return tail == REF_DEF_NAME or tail.split("#", 1)[0] == REF_SCHEMA_FILE


class TypeRecognizer:
    """Which published type a `$ref` in one schema names: REF, ANCHOR or None (feature 020).

    `DarnlinkRef` keeps the name match of `is_ref_type`. `DarnlinkAnchor` is recognised only by identity: a `$ref`
    whose fragment is `/$defs/DarnlinkAnchor` and whose base is the published `$id`, a local file whose own `$id` is
    that one (a pinned copy), or empty (the same document). Its name alone is not enough, and neither is its
    pattern: every lowercase uuid has the same pattern, and most uuids in data are foreign keys, not identities."""

    def __init__(self, schema_path: Optional[Path] = None):
        self._dir = schema_path.parent if schema_path is not None else None
        self._ids: Dict[Path, bool] = {}

    def kind(self, ref: object) -> Optional[str]:
        if not isinstance(ref, str):
            return None
        if is_ref_type(ref):
            return REF
        base, _, frag = ref.partition("#")
        if frag == f"/$defs/{ANCHOR_DEF_NAME}" and (not base or self._names_the_types(base)):
            return ANCHOR
        return None

    def _names_the_types(self, base: str) -> bool:
        if TYPES_ID.fullmatch(base):
            return True
        if self._dir is None or base.startswith(("http://", "https://")):
            return False
        path = (self._dir / base).resolve()
        if path not in self._ids:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                loaded = None
            self._ids[path] = isinstance(loaded, dict) and isinstance(loaded.get("$id"), str) \
                and TYPES_ID.fullmatch(loaded["$id"]) is not None
        return self._ids[path]

    def mentions(self, schema: object) -> bool:
        """True if some `$ref` anywhere in the schema names either type (see `mentions_ref_type`)."""
        stack = [schema]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if self.kind(node.get("$ref")):
                    return True
                stack += node.values()
            elif isinstance(node, list):
                stack += node
        return False


def _local_def(root_schema: dict, ref: str) -> Optional[dict]:
    """Resolve a same-document `$ref` (`#/a/b`), or None."""
    if not ref.startswith("#/"):
        return None
    node: object = root_schema
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, dict) else None


def _ptr(base: str, key: object) -> str:
    return f"{base}/{str(key).replace('~', '~0').replace('/', '~1')}"


def _at(doc: object, pointer: str) -> object:
    """The value at a JSON Pointer that `_ptr` built, or None."""
    node = doc
    for part in pointer.split("/")[1:] if pointer else []:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            node = next((v for k, v in node.items() if str(k) == part), None)
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def _matches(pattern: object, key: str) -> bool:
    """`re.search`, tolerant of a pattern Python cannot compile (JSON Schema regexes are ECMA-262)."""
    try:
        return isinstance(pattern, str) and re.search(pattern, key) is not None
    except re.error:
        return False


def ref_positions(instance: object, schema: dict,
                  recognizer: Optional[TypeRecognizer] = None) -> List[Tuple[str, object]]:
    """[(JSON Pointer, value)] of every position of `instance` whose schema node is the reference type."""
    return _typed_positions(instance, schema, REF, recognizer or TypeRecognizer())


def anchor_positions(instance: object, schema: dict,
                     recognizer: Optional[TypeRecognizer] = None) -> List[Tuple[str, object]]:
    """[(JSON Pointer, value)] of every position of `instance` whose schema node is `DarnlinkAnchor`, at any depth.
    Inside an `anyOf`/`oneOf` only a string counts (LinkML writes an optional slot as `anyOf: [<type>, null]`)."""
    return _typed_positions(instance, schema, ANCHOR, recognizer or TypeRecognizer())



def file_anchors(doc: object, schema: dict, recognizer: TypeRecognizer,
                 rel: str) -> Tuple[List[Tuple[str, str]], List[RefFinding], bool]:
    """The typed anchors of one parsed file: (good ones as (element pointer, uuid), an `invalid-anchor` finding per bad
    one, whether the bad ones include the file-level anchor). '' as the element pointer is the whole file."""
    good: List[Tuple[str, str]] = []
    bad: List[RefFinding] = []
    whole_file_bad = False
    for pointer, value in anchor_positions(doc, schema, recognizer):
        element = pointer.rsplit("/", 1)[0]
        problem = ""
        if not (isinstance(value, str) and CANONICAL_UUID.fullmatch(value)):
            problem = "an anchor must be a lowercase canonical uuid"
        elif not isinstance(_at(doc, element), dict):
            problem = "an anchor must be a key of the element it identifies, not an item of a list"
        if problem:
            bad.append(RefFinding(INVALID_ANCHOR, rel, pointer or "/", "", str(value), f"{problem}: not a link target"))
            whole_file_bad = whole_file_bad or not element
        else:
            good.append((element, value))
    return good, bad, whole_file_bad

def _typed_positions(instance: object, schema: dict, want: str,
                     recognizer: TypeRecognizer) -> List[Tuple[str, object]]:
    """[(JSON Pointer, value)] of every position of `instance` whose schema node is the type `want`.
    Follows same-document `$ref`s, `properties`, `patternProperties`, `additionalProperties`, `items` and
    the `allOf`/`anyOf`/`oneOf` branches; a position reached twice is reported once. Inside an `anyOf`/`oneOf`
    the reference type is only one alternative (LinkML writes an optional slot as `anyOf: [<type>, null]`), so
    there a value counts only if it looks like a reference: a mapping with a `link`, or with a `uuid` when no
    other alternative could take a mapping (so `{uuid, lnk}` in an optional slot is reported as malformed, while
    an entity with a `uuid` that another object alternative describes is left alone)."""
    found: Dict[str, object] = {}

    def walk(value: object, node: object, ptr: str, depth: int, alternative: str = "") -> None:
        # alternative: "" (not inside anyOf/oneOf), "lone" (no other branch takes a mapping) or "shared"
        if depth > MAX_DEPTH or not isinstance(node, dict):
            return
        ref = node.get("$ref")
        kind = recognizer.kind(ref)
        if kind:
            if kind != want:
                return
            if not alternative:
                found.setdefault(ptr, value)
            elif want == ANCHOR:
                if isinstance(value, str):
                    found.setdefault(ptr, value)
            elif isinstance(value, dict) and ("link" in value or ("uuid" in value and alternative == "lone")):
                found.setdefault(ptr, value)
            return
        if isinstance(ref, str):
            walk(value, _local_def(schema, ref), ptr, depth + 1, alternative)
        for key in ("allOf", "anyOf", "oneOf"):
            branches = node.get(key)
            branches = branches if isinstance(branches, list) else []
            for i, sub in enumerate(branches):
                if key == "allOf":
                    walk(value, sub, ptr, depth + 1, alternative)
                    continue
                shared = alternative == "shared" or any(_may_take_mapping(o) for j, o in enumerate(branches) if j != i)
                walk(value, sub, ptr, depth + 1, "shared" if shared else "lone")
        if isinstance(value, dict):
            props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
            patterns = node.get("patternProperties") if isinstance(node.get("patternProperties"), dict) else {}
            extra = node.get("additionalProperties")
            for k, v in value.items():
                if k in props:
                    walk(v, props[k], _ptr(ptr, k), depth + 1)
                    continue
                matched = [s for p, s in patterns.items() if isinstance(k, str) and _matches(p, k)]
                for sub in matched:
                    walk(v, sub, _ptr(ptr, k), depth + 1)
                if not matched and isinstance(extra, dict):
                    walk(v, extra, _ptr(ptr, k), depth + 1)
        elif isinstance(value, list) and isinstance(node.get("items"), dict):
            for i, v in enumerate(value):
                walk(v, node["items"], _ptr(ptr, i), depth + 1)

    walk(instance, schema, "", 0)
    return sorted(found.items())


_NOT_MAPPING_TYPES = {"null", "string", "integer", "number", "boolean", "array"}


def _may_take_mapping(branch: object) -> bool:
    """False only for a branch that certainly rejects a mapping: one whose `type` names no `object`."""
    if not isinstance(branch, dict) or is_ref_type(branch.get("$ref")):
        return not isinstance(branch, dict)
    types = branch.get("type")
    types = [types] if isinstance(types, str) else types
    return not (isinstance(types, list) and types and set(types) <= _NOT_MAPPING_TYPES)


def mentions_ref_type(schema: object) -> bool:
    """True if some `$ref` anywhere in the schema names the reference type. A schema without one declares no
    reference, so its YAML files need not even load. No depth limit: a parsed JSON file is a finite tree, and a
    limit here shorter than the one of `ref_positions` would skip a deep reference in silence."""
    stack = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if is_ref_type(node.get("$ref")):
                return True
            stack += node.values()
        elif isinstance(node, list):
            stack += node
    return False


@dataclass
class TargetIndex:
    """uuid -> file, over `.md` frontmatter, YAML top-level `uuid` and typed anchors in YAML. A uuid declared twice
    (two files, or two elements of one file) is ambiguous. `pointers` holds, for an anchor that identifies an element
    inside a file rather than the whole file, the JSON Pointer of that element."""
    by_uuid: Dict[str, Path]
    duplicates: Dict[str, List[Path]]
    pointers: Dict[str, str] = field(default_factory=dict)
    #: resolved file -> its anchors as (element pointer, uuid), duplicates included: the candidates of a `link`.
    files: Dict[Path, List[Tuple[str, str]]] = field(default_factory=dict)

    def get(self, uuid: str) -> Optional[Path]:
        return self.by_uuid.get(uuid.lower())

    def element(self, uuid: str) -> str:
        """JSON Pointer of the element the uuid identifies, or '' when it identifies the whole file."""
        return self.pointers.get(uuid.lower(), "")

    def is_ambiguous(self, uuid: str) -> bool:
        return uuid.lower() in self.duplicates

    def candidates(self, target: Path, fragment: str) -> List[str]:
        """The uuids a `link` to `target#fragment` can mean (step 3). A JSON Pointer fragment names one element;
        otherwise the file's own anchor counts, and only when the file has none, its element anchors."""
        anchors = self.files.get(resolved(target), [])
        if fragment.startswith("/"):
            pointer = unquote(fragment)
            return sorted({u for element, u in anchors if element == pointer})
        whole = sorted({u for element, u in anchors if not element})
        if whole or fragment:   # a heading fragment (`README.md#usage`) still names the whole file
            return whole
        return sorted({u for _, u in anchors})


def build_target_index(root: Path, excludes: set[str], yaml_docs: Dict[Path, object],
                       anchors: Optional[Dict[Path, List[Tuple[str, str]]]] = None) -> TargetIndex:
    """`anchors` maps a YAML file to its typed anchors, as (element pointer, uuid); '' is the whole file."""
    md = build_index(root, excludes)
    by_uuid = dict(md.by_uuid)
    duplicates = {u: list(ps) for u, ps in md.duplicates.items()}
    pointers: Dict[str, str] = {}
    files: Dict[Path, List[Tuple[str, str]]] = {}
    for u, p in md.by_uuid.items():
        files.setdefault(resolved(p), []).append(("", u))
    for u, ps in md.duplicates.items():
        for p in ps:
            files.setdefault(resolved(p), []).append(("", u))
    seen: set = set()

    def add(path: Path, element: str, u: str) -> None:
        if (path, element, u) in seen:   # a top-level `uuid` that the schema also types as an anchor
            return
        seen.add((path, element, u))
        files.setdefault(resolved(path), []).append((element, u))
        if u in duplicates:
            duplicates[u].append(path)
        elif u in by_uuid:
            duplicates[u] = [by_uuid.pop(u), path]
            pointers.pop(u, None)
        else:
            by_uuid[u] = path
            if element:
                pointers[u] = element

    for path, doc in yaml_docs.items():
        u = doc.get("uuid") if isinstance(doc, dict) else None
        if isinstance(u, str) and u.strip():
            add(path, "", u.strip().lower())
    for path, items in (anchors or {}).items():
        for element, u in items:
            add(path, element, u)
    return TargetIndex(by_uuid, duplicates, pointers, files)


def _shown(path: Path, root: Path) -> str:
    try:
        return resolved(path).relative_to(resolved(root)).as_posix()
    except ValueError:
        return path.as_posix()


def _same(a: Path, b: Path) -> bool:
    return resolved(a) == resolved(b)


def judge(value: object, yaml_file: Path, index: TargetIndex, root: Path) -> Tuple[str, str, str, str, str]:
    """(kind, link, uuid, detail, new_link) for one reference value. `root` only shortens the paths in `detail`.
    For a `fillable` reference, `uuid` is the one to write."""
    if isinstance(value, dict) and "uuid" not in value and isinstance(value.get("link"), str) and value["link"].strip():
        return _judge_missing_uuid(value["link"], yaml_file, index, root)
    if not isinstance(value, dict) or not isinstance(value.get("uuid"), str) or not isinstance(value.get("link"), str):
        return MALFORMED, str(value.get("link", "")) if isinstance(value, dict) else "", "", \
            "not a {uuid, link} mapping of strings", ""
    if not value["link"].strip() or not value["uuid"].strip():
        return MALFORMED, value["link"], value["uuid"], "empty link or uuid", ""
    link, uuid = value["link"], value["uuid"].strip()
    if is_web_href(link):
        return OK, link, uuid, "web link: not checked here", ""
    if index.is_ambiguous(uuid):
        return AMBIGUOUS, link, uuid, "uuid is declared by more than one file", ""
    target = index.get(uuid)
    if target is None:
        return UNRESOLVABLE, link, uuid, "no file declares this uuid", ""
    points = resolve_href(link, yaml_file)
    if points.is_dir():
        points = points / "README.md"   # a directory link: its target is the README.md inside
    shown = _shown(target, root)
    path_part, fragment = split_fragment(link)
    element = index.element(uuid)
    # An anchor of one element of a file (feature 020): the fragment is the JSON Pointer of that element, and it is
    # repaired like the path. A whole-file anchor leaves the fragment alone (a Markdown heading, say).
    want = element or fragment
    if _same(points, target):
        if fragment == want or (element and unquote(fragment) == element):   # `%20` in a link is a space
            return OK, link, uuid, "", ""
        return REPAIR, link, uuid, f"the element moved to #{element} in {shown}", f"{path_part}#{want}"
    if points.is_file():
        return CONFLICT, link, uuid, f"path names an existing file, but the uuid lives in {shown}", ""
    where = f"{shown}#{element}" if element else shown
    return REPAIR, link, uuid, f"target moved to {where}", relative_link(target, yaml_file, want)


def _judge_missing_uuid(link: str, yaml_file: Path, index: TargetIndex, root: Path) -> Tuple[str, str, str, str, str]:
    """A `{link}` with no `uuid` key (step 3): `fillable` with exactly one candidate anchor, never for a web link."""
    if is_web_href(link):
        return MALFORMED, link, "", "no uuid: a web link is never filled", ""
    points = resolve_href(link, yaml_file)
    if points.is_dir():
        points = points / "README.md"   # a directory link: its target is the README.md inside
    if not points.is_file():
        return MALFORMED, link, "", "no uuid, and the link names no file", ""
    _, fragment = split_fragment(link)
    shown = _shown(points, root)
    found = index.candidates(points, fragment)
    if not found:
        at = f" at #{fragment}" if fragment.startswith("/") else ""
        return MALFORMED, link, "", f"no uuid, and {shown} has no anchor{at}", ""
    if len(found) > 1:
        return AMBIGUOUS, link, "", f"no uuid, and {shown} has {len(found)} candidate anchors", ""
    if index.is_ambiguous(found[0]):
        return AMBIGUOUS, link, found[0], "no uuid, and the target's uuid is declared by more than one file", ""
    return FILLABLE, link, found[0], f"no uuid: {shown} declares {found[0]}", ""


_LINK_LINE = r"^(\s*(?:-\s+)?link:\s*)(['\"]?){old}\2(\s*(?:#.*)?)$"
# A comma or a bracket anywhere is quoted too: harmless in block style, and it would end the value inside {}.
_NEEDS_QUOTES = re.compile(r"(^[-?:\[\]{}#&*!|>'\"%@`\s])|(:\s)|(\s#)|(\s$)|[,\[\]{}]")


def _quoted(new: str, quote: str) -> str:
    """`new` written inside `quote` (none, `'` or `"`), escaped the way YAML reads that style."""
    if quote == "'":
        return "'" + new.replace("'", "''") + "'"
    if quote == '"':
        return '"' + new.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return new


def apply_repairs(path: Path, repairs: List[RefFinding]) -> List[RefFinding]:
    """Rewrite each repaired `link:` line of `path`, keeping the rest of the file byte for byte.
    The rewrite works on lines, not on positions, so a link text is only rewritten when EVERY `link:` line
    carrying it in this file is one of these repairs, all with the same new path. If the same text also
    appears at a position the schema does not declare, or at a reference that is not being repaired, it is
    left as is and returned, to be fixed by hand. The text is also counted as a plain substring, so a file that
    mentions it anywhere else (`../README.md` holds `README.md`) is left to the reader too.
    The new text must load as YAML again and hold every new link; if not, nothing is written and every repair
    is returned."""
    from .frontmatter_edit import read_text_keep_newlines, write_text_keep_newlines

    by_old: Dict[str, set] = {}
    for f in repairs:
        by_old.setdefault(f.link, set()).add(f.new_link)
    text = original = read_text_keep_newlines(path)
    left = []
    for old, news in by_old.items():
        if len(news) != 1:
            left += [f for f in repairs if f.link == old]
            continue
        new = next(iter(news))
        mine = [f for f in repairs if f.link == old]
        pattern = re.compile(_LINK_LINE.format(old=re.escape(old)), re.MULTILINE)
        if len(pattern.findall(text)) != len(mine) or text.count(old) != len(mine):
            # Lines and positions are matched by COUNT, so both counts must equal the repairs: every `link:` line
            # with this text, and every appearance of the text anywhere in the file (a flow mapping, another key,
            # a comment). Anything else -- a repair in a flow mapping while an undeclared `link:` line has the
            # same text, say -- is left to the reader, never guessed
            left += mine
            continue

        def sub(m: re.Match) -> str:
            quote = m.group(2) or ('"' if _NEEDS_QUOTES.search(new) else "")
            return f"{m.group(1)}{_quoted(new, quote)}{m.group(3)}"

        text = pattern.sub(sub, text)
    if text != original and not _rewrite_is_exact(original, text, [f for f in repairs if f not in left]):
        return list(repairs)
    write_text_keep_newlines(path, text)
    return left


#: A block-style `link:` line whose value is `old`, as `apply_fills` reads it (one line, its ending stripped).
_FILL_LINE = r"([ \t]*)(-[ \t]+)?link:[ \t]*(['\"]?){old}\3[ \t]*(?:#.*)?"


def apply_fills(path: Path, fills: List[RefFinding]) -> List[RefFinding]:
    """Insert `uuid: <value>` under the `link:` line of each `fillable` reference of `path`, keeping every other byte.
    As for repairs, a link text is filled only when every appearance of it in the file is one of these references,
    all with the same uuid and each on a block-style `link:` line of its own; the rest is returned to the reader. The
    new text must load as the original document plus exactly those `uuid` keys, or nothing is written."""
    from .frontmatter_edit import read_text_keep_newlines, write_text_keep_newlines

    original = read_text_keep_newlines(path)
    lines = re.findall(r"[^\n]*\n|[^\n]+\Z", original)
    newline = "\r\n" if "\r\n" in original else "\n"
    by_old: Dict[str, set] = {}
    for f in fills:
        by_old.setdefault(f.link, set()).add(f.uuid)
    left: List[RefFinding] = []
    inserts: Dict[int, str] = {}
    for old, uuids in by_old.items():
        mine = [f for f in fills if f.link == old]
        pattern = re.compile(_FILL_LINE.format(old=re.escape(old)))
        at = [i for i, line in enumerate(lines) if pattern.fullmatch(line.rstrip("\r\n"))]
        if len(uuids) != 1 or len(at) != len(mine) or original.count(old) != len(mine):
            left += mine   # the same counting rule as `apply_repairs`: anything else is left, never guessed
            continue
        u = next(iter(uuids))
        for i in at:
            m = pattern.fullmatch(lines[i].rstrip("\r\n"))
            inserts[i] = " " * (len(m.group(1).expandtabs()) + len(m.group(2) or "")) + f"uuid: {u}"
    if not inserts:
        return list(fills)
    out = []
    for i, line in enumerate(lines):
        if i in inserts:
            body = line.rstrip("\r\n")
            eol = line[len(body):]
            out += [line, inserts[i] + eol] if eol else [line + newline, inserts[i]]
        else:
            out.append(line)
    text = "".join(out)
    written = [f for f in fills if f not in left]
    if not _fill_is_exact(original, text, written):
        return list(fills)
    write_text_keep_newlines(path, text)
    return left


def _fill_is_exact(original: str, text: str, written: List[RefFinding]) -> bool:
    """True if `text` loads as the original document with a `uuid` added to each filled reference and nothing else."""
    import yaml
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    try:
        before = yaml.load(original.lstrip("﻿"), Loader=loader)
        after = yaml.load(text.lstrip("﻿"), Loader=loader)
    except Exception:
        return False
    for f in written:
        value = _at(before, "" if f.pointer == "/" else f.pointer)
        if not isinstance(value, dict) or "uuid" in value:
            return False
        value["uuid"] = f.uuid
    return before == after


def _at(doc: object, pointer: str) -> object:
    """The value at a JSON Pointer of `ref_positions`, or None if the path is not there."""
    node = doc
    for part in [s.replace("~1", "/").replace("~0", "~") for s in pointer.split("/")[1:]]:
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict):
            keys = [k for k in node if str(k) == part]
            if len(keys) != 1:
                return None
            node = node[keys[0]]
        else:
            return None
    return node


def _rewrite_is_exact(original: str, text: str, written: List[RefFinding]) -> bool:
    """True if `text` loads as YAML and equals the original document with exactly the written changes: each
    repaired reference holds its new link at its own position, and no other value moved. A same text
    rewritten somewhere else (a link written escaped at the declared position and plain at an undeclared
    one, say) fails here."""
    import yaml
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    try:
        before = yaml.load(original.lstrip("\ufeff"), Loader=loader)
        after = yaml.load(text.lstrip("\ufeff"), Loader=loader)
    except Exception:
        return False
    for f in written:
        value = _at(before, "" if f.pointer == "/" else f.pointer)
        if not isinstance(value, dict):
            return False
        value["link"] = f.new_link
    return before == after


def plan(root: Path, excludes: set[str] = DEFAULT_EXCLUDES) -> Tuple[List[RefFinding], Dict[str, int]]:
    """Check every typed reference under `root`. Returns (findings that are not `ok`, counters).
    A modeline that names a local schema which cannot be read is a finding too: otherwise a gate would pass
    green having checked nothing."""
    from .paths import resolve_cache
    with resolve_cache():
        return _plan(root.resolve(), excludes)


def _plan(root: Path, excludes: set[str]) -> Tuple[List[RefFinding], Dict[str, int]]:
    files = list(iter_yaml_files(root, excludes))
    docs = {p: _load_yaml(p) for p in files}
    schemas: Dict[Path, Optional[dict]] = {}
    recognizers: Dict[Path, TypeRecognizer] = {}
    typed: Dict[Path, bool] = {}
    stats = {"yaml_files": len(files), "with_schema": 0, "references": 0, "ok": 0, "anchors": 0}
    findings: List[RefFinding] = []
    anchors: Dict[Path, List[Tuple[str, str]]] = {}
    not_targets: set = set()
    checked: List[Tuple[Path, str, dict, TypeRecognizer]] = []
    for path in files:
        decl = modeline_schema(path)
        if not decl or decl.startswith(("http://", "https://")):
            continue
        spath = (path.parent / decl).resolve()
        if spath not in schemas:
            try:
                loaded = json.loads(spath.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                loaded = None
            schemas[spath] = loaded if isinstance(loaded, dict) else None
        schema = schemas[spath]
        rel = path.relative_to(root).as_posix()
        if schema is None:
            findings.append(RefFinding(NO_SCHEMA, rel, "/", "", "", f"the modeline names {decl}, which is not a "
                                                                        "readable JSON object"))
            continue
        recognizer = recognizers.setdefault(spath, TypeRecognizer(spath))
        if spath not in typed:
            typed[spath] = recognizer.mentions(schema)
        if not typed[spath]:
            continue
        if docs[path] is UNREADABLE_DOC:
            findings.append(RefFinding(UNREADABLE, rel, "/", "", "", "the file has a schema modeline but does not "
                                                                         "load as one YAML document"))
            continue
        stats["with_schema"] += 1
        good, bad, whole_file_bad = file_anchors(docs[path], schema, recognizer, rel)
        stats["anchors"] += len(good) + len(bad)
        findings += bad
        if whole_file_bad:
            not_targets.add(path)   # its top-level `uuid` is this same invalid anchor
        if good:
            anchors[path] = good
        checked.append((path, rel, schema, recognizer))
    # JSON files and code `#---` blocks are targets too (step 2). YAML was read above, with its untyped top-level `uuid`.
    from .typed_anchors import collect
    extra = collect(root, excludes, kinds=("json", "code"))
    findings += extra.findings
    for path, items in extra.anchors.items():
        have = anchors.setdefault(path, [])
        added = [item for item in items if item not in have]   # a YAML file's block may repeat its typed `uuid`
        have += added
        stats["anchors"] += len(added)
    # Anchors first, references after: a reference may point to an anchor in a file read later.
    index = build_target_index(root, excludes, {p: d for p, d in docs.items() if p not in not_targets}, anchors)
    for path, rel, schema, recognizer in checked:
        for pointer, value in ref_positions(docs[path], schema, recognizer):
            stats["references"] += 1
            kind, link, uuid, detail, new = judge(value, path, index, root)
            if kind == OK:
                stats["ok"] += 1
            else:
                findings.append(RefFinding(kind, rel, pointer or "/", link, uuid, detail, new))
    return findings, stats


def run_cli(argv: List[str]) -> int:
    """`darnlink yaml-refs [ROOT] [--exclude NAME]... [--write] [--json]`.
    rc 0: every reference is correct (or was repaired with --write); 2: some reference is broken; 1: usage."""
    ap = argparse.ArgumentParser(prog="darnlink yaml-refs",
                                 description="check (and with --write, repair) typed {uuid, link} references in YAML "
                                             "files, at the positions their JSON Schema declares as DarnlinkRef")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--exclude", action="append", default=[], help="directory name or glob to skip (repeatable)")
    ap.add_argument("--write", action="store_true", help="rewrite repairable links in place")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 1
    root = Path(args.root)
    if not root.is_dir():
        print(f"darnlink yaml-refs: not a directory: {root}", file=sys.stderr)
        return 1
    excludes = set(DEFAULT_EXCLUDES) | set(args.exclude)
    findings, stats = plan(root, excludes)
    repaired: List[RefFinding] = []
    filled: List[RefFinding] = []
    if args.write:
        for kind, apply, done in ((REPAIR, apply_repairs, repaired), (FILLABLE, apply_fills, filled)):
            by_file: Dict[str, List[RefFinding]] = {}
            for f in findings:
                if f.kind == kind:
                    by_file.setdefault(f.file, []).append(f)
            for rel, items in by_file.items():
                left = apply(root.resolve() / rel, items)
                done += [f for f in items if f not in left]
        findings = [f for f in findings if f not in repaired and f not in filled]
    if args.json:
        print(json.dumps({"stats": stats, "findings": [asdict(f) for f in findings],
                          "repaired": [asdict(f) for f in repaired], "filled": [asdict(f) for f in filled]},
                         ensure_ascii=False, indent=2))
    else:
        for f in repaired:
            print(f"REPAIRED     {f.file}#{f.pointer}  {f.link} -> {f.new_link}")
        for f in filled:
            print(f"FILLED       {f.file}#{f.pointer}  {f.link}  uuid: {f.uuid}")
        for f in findings:
            extra = f"  -> {f.new_link}" if f.new_link else ""
            print(f"{f.kind.upper():<12} {f.file}#{f.pointer}  {f.link}  ({f.detail}){extra}")
        print(f"darnlink yaml-refs: {stats['references']} references in {stats['with_schema']} YAML files with a "
              f"local schema ({stats['yaml_files']} scanned): {stats['ok']} ok, {len(repaired)} repaired, "
              f"{len(filled)} filled, {len(findings)} broken")
    return 2 if findings else 0
