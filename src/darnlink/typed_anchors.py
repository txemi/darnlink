"""Typed anchors outside Markdown, as link targets (feature 020, step 2).

A file that is not Markdown is a link target only where its schema, or a fixed block of the file, says it carries
an anchor. A value that merely looks like a uuid is not one: most uuids in data are foreign keys, not identities.
Three kinds of file qualify:

- a YAML file whose modeline names a local JSON Schema: every `DarnlinkAnchor` position (`yaml_refs.file_anchors`);
- a JSON file whose `$schema` key names a local JSON Schema: the same positions;
- any other file whose leading `#` comment lines hold a block between two `#---` lines: the `uuid` key of that block
  is the anchor of the whole file (Python, shell, YAML, TOML, Ruby; other comment syntaxes are a later feature).

The untyped top-level `uuid` of a YAML file is NOT collected here. `yaml-refs` keeps it as a target for references
from YAML (step 1), but Markdown links resolve only against typed anchors: in a real tree a YAML file often repeats
the `uuid` of the README beside it (both describe the same entity), and counting it would turn every Markdown link
to that README into `ambiguous`. Measured on 2026-10-29 in a fleet repository: 137 such pairs.

The scan follows the Markdown rules: excluded directory names are skipped, each file is visited once under its
canonical path, a symlink out of the root is not a target (`TypedAnchors.out_of_root` lists it), and a file carrying the
`<!-- darnlink-ignore-file -->` marker is not a target (for a code file, in its leading comment lines).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .frontmatter_index import DEFAULT_EXCLUDES, FrontmatterIndex, dir_excluded
from .links import _IGNORE_FILE_RE
from .yaml_refs import (CANONICAL_UUID, INVALID_ANCHOR, NO_SCHEMA, UNREADABLE, UNREADABLE_DOC, YAML_SUFFIXES,
                        RefFinding, TypeRecognizer, file_anchors, modeline_schema)

#: The line that opens and closes the anchor block of a code file, among its leading comment lines.
CODE_FENCE = "#---"
#: How much of a file is read to find its leading comment lines. A block further down is not an anchor.
HEAD_BYTES = 64 * 1024
#: A larger JSON file is not read: data that size is not a document anyone links to by hand.
JSON_MAX_BYTES = 8 * 1024 * 1024
KINDS = ("yaml", "json", "code")


@dataclass
class TypedAnchors:
    """What `collect` found. `anchors` maps a file to its good anchors as (element pointer, uuid); '' is the whole
    file. `findings` are the anchors that are not targets, and why (`yaml-refs` reports them)."""
    anchors: Dict[Path, List[Tuple[str, str]]] = field(default_factory=dict)
    findings: List[RefFinding] = field(default_factory=list)
    out_of_root: List[Path] = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(len(items) for items in self.anchors.values())


def iter_data_files(root: Path, excludes: set = DEFAULT_EXCLUDES,
                    out_of_root: Optional[List[Path]] = None) -> Iterator[Path]:
    """Every file under `root` that is not Markdown, once, under its canonical path (`iter_markdown_files` rules)."""
    root = root.resolve()
    inside = str(root).rstrip(os.sep) + os.sep   # a string test: `Path.is_relative_to` cost seconds on a big tree
    seen: set = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not dir_excluded(d, excludes))
        for fn in sorted(filenames):
            if fn.lower().endswith(".md"):
                continue
            path = Path(dirpath) / fn
            try:
                real = path.resolve(strict=True)
            except OSError:
                continue
            if real in seen or not real.is_file():
                continue
            if not str(real).startswith(inside):
                if out_of_root is not None:
                    out_of_root.append(path)
                continue
            seen.add(real)
            yield real


def leading_comments(text: str) -> List[str]:
    """The leading lines of `text` that start with `#` (a shebang is one), without their line ends."""
    out: List[str] = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        out.append(line)
    return out


def code_block(text: str) -> Optional[str]:
    """The YAML text of the block between the first two `#---` lines among the leading comments, or None.
    Each line loses its `#` and one space after it, if any."""
    lines = leading_comments(text)
    fences = [n for n, line in enumerate(lines) if line.rstrip() == CODE_FENCE]
    if len(fences) < 2:
        return None
    body = [line[1:] for line in lines[fences[0] + 1:fences[1]]]
    return "\n".join(b[1:] if b.startswith(" ") else b for b in body)


def _code_anchor(path: Path, head: str, rel: str, found: TypedAnchors) -> None:
    block = code_block(head)
    if block is None or _IGNORE_FILE_RE.search("\n".join(leading_comments(head))):
        return
    import yaml
    try:
        data = yaml.safe_load(block)
    except Exception:
        found.findings.append(RefFinding(UNREADABLE, rel, "/", "", "", f"the {CODE_FENCE} block is not YAML"))
        return
    value = data.get("uuid") if isinstance(data, dict) else None
    if value is None:
        return   # a block without a `uuid` (other metadata) declares no anchor
    if isinstance(value, str) and CANONICAL_UUID.fullmatch(value):
        found.anchors.setdefault(path, []).append(("", value))
    else:
        found.findings.append(RefFinding(INVALID_ANCHOR, rel, "/uuid", "", str(value),
                                         "an anchor must be a lowercase canonical uuid: not a link target"))


class _Schemas:
    """Local JSON Schemas read once each, with their type recognisers."""

    def __init__(self) -> None:
        self._loaded: Dict[Path, Optional[dict]] = {}
        self._recognizers: Dict[Path, TypeRecognizer] = {}
        self._typed: Dict[Path, bool] = {}

    def get(self, path: Path) -> Tuple[Optional[dict], Optional[TypeRecognizer]]:
        """(schema, recognizer) for a schema that declares an anchor or reference type; (None, None) for one that
        declares neither; ({}, None) for one that cannot be read."""
        if path not in self._loaded:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                loaded = None
            self._loaded[path] = loaded if isinstance(loaded, dict) else None
        schema = self._loaded[path]
        if schema is None:
            return {}, None
        recognizer = self._recognizers.setdefault(path, TypeRecognizer(path))
        if path not in self._typed:
            self._typed[path] = recognizer.mentions(schema)
        return (schema, recognizer) if self._typed[path] else (None, None)


def _typed_schema(path: Path, decl: str, rel: str, schemas: _Schemas,
                  found: TypedAnchors) -> Tuple[Optional[dict], Optional[TypeRecognizer]]:
    """The schema a file names, if it declares a type; asked BEFORE the file is parsed, so the many data files whose
    schema declares no anchor are never loaded (measured on a fleet repository: 1,556 YAML files, 8 s)."""
    schema, recognizer = schemas.get((path.parent / decl).resolve())
    if schema == {}:
        found.findings.append(RefFinding(NO_SCHEMA, rel, "/", "", "", f"the file names the schema {decl}, which is "
                                                                         "not a readable JSON object"))
        return None, None
    return schema, recognizer


def _schema_anchors(doc: object, schema: dict, recognizer: TypeRecognizer, path: Path, rel: str,
                    found: TypedAnchors) -> None:
    if doc is UNREADABLE_DOC:
        found.findings.append(RefFinding(UNREADABLE, rel, "/", "", "", "the file names a schema but does not load"))
        return
    good, bad, _ = file_anchors(doc, schema, recognizer, rel)
    found.findings += bad
    if good:
        found.anchors.setdefault(path, []).extend(good)


def _is_local(decl: object) -> bool:
    return isinstance(decl, str) and bool(decl.strip()) and not decl.startswith(("http://", "https://"))


def collect(root: Path, excludes: set = DEFAULT_EXCLUDES, kinds: Tuple[str, ...] = KINDS) -> TypedAnchors:
    """The typed anchors under `root`, of the kinds asked for: "yaml", "json", "code"."""
    root = root.resolve()
    found = TypedAnchors()
    schemas = _Schemas()
    for path in iter_data_files(root, excludes, found.out_of_root):
        rel = path.relative_to(root).as_posix()
        name = path.name.lower()
        try:
            if name.endswith(".json"):
                if "json" in kinds and path.stat().st_size <= JSON_MAX_BYTES:
                    _json_file(path, rel, schemas, found)
                continue
            with path.open("rb") as fh:
                raw = fh.read(HEAD_BYTES)
        except OSError:
            continue
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        if not raw.startswith(b"#") and not (name.endswith(YAML_SUFFIXES) and raw.startswith(b"---")):
            continue   # no leading comment: neither a modeline nor a code block
        head = raw.decode("utf-8", errors="replace")
        if name.endswith(YAML_SUFFIXES) and "yaml" in kinds:
            _yaml_file(path, rel, schemas, found)
        if "code" in kinds:
            _code_anchor(path, head, rel, found)
    return found


def _yaml_file(path: Path, rel: str, schemas: _Schemas, found: TypedAnchors) -> None:
    decl = modeline_schema(path)
    if not _is_local(decl):
        return
    schema, recognizer = _typed_schema(path, decl, rel, schemas, found)
    if schema is None:
        return
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if _IGNORE_FILE_RE.search(text):
        return
    import yaml
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    try:
        doc = yaml.load(text, Loader=loader)
    except Exception:
        doc = UNREADABLE_DOC
    _schema_anchors(doc, schema, recognizer, path, rel, found)


def _json_file(path: Path, rel: str, schemas: _Schemas, found: TypedAnchors) -> None:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if '"$schema"' not in text or _IGNORE_FILE_RE.search(text):
        return
    try:
        doc = json.loads(text)
    except ValueError:
        return   # without a parsed `$schema` the file declares nothing; JSON syntax is another gate's job
    decl = doc.get("$schema") if isinstance(doc, dict) else None
    if _is_local(decl):
        schema, recognizer = _typed_schema(path, decl, rel, schemas, found)
        if schema is not None:
            _schema_anchors(doc, schema, recognizer, path, rel, found)


def with_typed_anchors(index: FrontmatterIndex, anchors: Dict[Path, List[Tuple[str, str]]]) -> FrontmatterIndex:
    """A copy of a Markdown index with the typed anchors added as targets. A uuid declared twice, by any two files
    or two elements, is ambiguous, as between two Markdown files."""
    merged = FrontmatterIndex(by_uuid=dict(index.by_uuid),
                              duplicates={u: list(ps) for u, ps in index.duplicates.items()},
                              invalid=list(index.invalid), out_of_root=list(index.out_of_root),
                              pointers=dict(index.pointers))
    for path, items in anchors.items():
        for element, u in items:
            merged.typed_anchors += 1
            if u in merged.duplicates:
                merged.duplicates[u].append(path)
            elif u in merged.by_uuid:
                if merged.by_uuid[u] == path and merged.pointers.get(u, "") == element:
                    continue
                merged.duplicates[u] = [merged.by_uuid.pop(u), path]
                merged.pointers.pop(u, None)
            else:
                merged.by_uuid[u] = path
                if element:
                    merged.pointers[u] = element
    return merged
