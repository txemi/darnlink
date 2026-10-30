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
import re
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
#: A larger JSON, YAML or schema file is not read: data that size is not a document anyone links to by hand.
DATA_MAX_BYTES = 8 * 1024 * 1024
KINDS = ("yaml", "json", "code")
_LINE_END = re.compile(r"\r\n|\r|\n")
#: A block line that tries to declare the anchor: only then is a block that is not YAML reported.
_UUID_LINE = re.compile(r"^\s*['\"]?uuid['\"]?\s*:", re.MULTILINE)
#: A URI scheme (`file:`, `urn:`): two letters at least, so a Windows drive (`C:`) is still a path.
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")


@dataclass
class TypedAnchors:
    """What `collect` found. `anchors` maps a file to its good anchors as (element pointer, uuid); '' is the whole
    file. `findings` are the anchors that are not targets, and why (`yaml-refs` reports them). `code` holds the
    (file, uuid) of each `#---` block anchor: a file declares it without adopting a schema, so it gives way to a
    Markdown frontmatter with the same uuid instead of making the links to that Markdown file ambiguous."""
    anchors: Dict[Path, List[Tuple[str, str]]] = field(default_factory=dict)
    findings: List[RefFinding] = field(default_factory=list)
    out_of_root: List[Path] = field(default_factory=list)
    code: set = field(default_factory=set)

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
    # Only \n, \r\n and \r end a line: `str.splitlines` also splits on U+2028, U+0085 and form feed, which would cut
    # a comment line in two and lose the block without a word.
    for line in _LINE_END.split(text):
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
        if _UUID_LINE.search(block):   # a decorative banner between two fences declares nothing: not a finding
            found.findings.append(RefFinding(UNREADABLE, rel, "/", "", "", f"the {CODE_FENCE} block is not YAML"))
        return
    value = data.get("uuid") if isinstance(data, dict) else None
    if value is None:
        return   # a block without a `uuid` (other metadata) declares no anchor
    if isinstance(value, str) and CANONICAL_UUID.fullmatch(value):
        _add(found, path, [("", value)])
        found.code.add((path, value))
    else:
        found.findings.append(RefFinding(INVALID_ANCHOR, rel, f"{CODE_FENCE}/uuid", "", str(value),
                                         f"the uuid of the {CODE_FENCE} block must be a lowercase canonical uuid: "
                                         "not a link target"))


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
            try:   # a regular file of a sane size only: `$schema` may name `/dev/zero` or a fifo
                loaded = json.loads(path.read_text(encoding="utf-8-sig")) \
                    if path.is_file() and path.stat().st_size <= DATA_MAX_BYTES else None
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


def _typed_schema(path: Path, decl: str, rel: str, schemas: _Schemas, found: TypedAnchors,
                  report: bool = True) -> Tuple[Optional[dict], Optional[TypeRecognizer]]:
    """The schema a file names, if it declares a type; asked BEFORE the file is parsed, so the many data files whose
    schema declares no anchor are never loaded (measured on a fleet repository: 1,556 YAML files, 8 s).
    An unreadable schema is a finding only with `report`: a YAML modeline names a schema for darnlink's kind of tools,
    while the `$schema` of any JSON configuration may name a file that is simply not there."""
    base = decl.split("#", 1)[0]
    if "\0" in base:   # no system names a file with a NUL; resolving one raises on Linux but not on Windows with 3.13,
        raise ValueError("the schema path has a NUL character")   # so it is said here, the same everywhere
    schema, recognizer = schemas.get((path.parent / base).resolve())
    if schema == {}:
        if report:
            found.findings.append(RefFinding(NO_SCHEMA, rel, "/", "", "", f"the file names the schema {decl}, which "
                                                                             "is not a readable JSON object"))
        return None, None
    return schema, recognizer


def _schema_anchors(doc: object, schema: dict, recognizer: TypeRecognizer, path: Path, rel: str,
                    found: TypedAnchors) -> None:
    if doc is UNREADABLE_DOC:
        found.findings.append(RefFinding(UNREADABLE, rel, "/", "", "", "the file names a schema but does not load"))
        return
    good, bad, _ = file_anchors(doc, schema, recognizer, rel)
    found.findings += bad
    _add(found, path, good)
    for _, u in good:   # the block repeats a typed anchor: the schema adopted it, so it no longer gives way
        found.code.discard((path, u))


def _add(found: TypedAnchors, path: Path, items: List[Tuple[str, str]]) -> None:
    """Add anchors to a file, once each: a YAML file may declare the same uuid in a typed field and in its block."""
    have = found.anchors.setdefault(path, [])
    have += [item for item in items if item not in have]
    if not have:
        del found.anchors[path]


def _is_local(decl: object) -> bool:
    """A `$schema` that names a local file: not a URI (`https:`, `file:`, `urn:`), not only a fragment."""
    return isinstance(decl, str) and bool(decl.split("#", 1)[0].strip()) and not _URI_SCHEME.match(decl)


def collect(root: Path, excludes: set = DEFAULT_EXCLUDES, kinds: Tuple[str, ...] = KINDS) -> TypedAnchors:
    """The typed anchors under `root`, of the kinds asked for: "yaml", "json", "code"."""
    root = root.resolve()
    found = TypedAnchors()
    schemas = _Schemas()
    for path in iter_data_files(root, excludes, found.out_of_root):
        rel = path.relative_to(root).as_posix()
        try:
            _one_file(path, rel, kinds, schemas, found)
        except OSError:
            continue   # a file that cannot be opened (mode 000, gone meanwhile) declares nothing anyone can see
        except Exception as e:   # one hostile file (a NUL in `$schema`, JSON nested past the recursion limit) never
            found.findings.append(RefFinding(UNREADABLE, rel, "/", "", "",   # aborts check, repair or yaml-refs
                                             f"could not be read for anchors: {type(e).__name__}"))
    return found


def _one_file(path: Path, rel: str, kinds: Tuple[str, ...], schemas: _Schemas, found: TypedAnchors) -> None:
    name = path.name.lower()
    with path.open("rb") as fh:
        if name.endswith(".json"):
            # `$schema` is looked for in the head first: most JSON files name none, and need not be read whole
            if "json" in kinds and b'"$schema"' in fh.read(HEAD_BYTES) and path.stat().st_size <= DATA_MAX_BYTES:
                _json_file(path, rel, schemas, found)
            return
        first = fh.read(4)   # one look at the start skips binaries and most code without reading 64 KiB of each
        if first.startswith(b"\xef\xbb\xbf"):
            first = first[3:]
        if not first.startswith(b"#") and not (name.endswith(YAML_SUFFIXES) and first.startswith(b"-")):
            return   # no leading comment: neither a modeline nor a code block
        fh.seek(0)
        raw = fh.read(HEAD_BYTES)
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if not raw.startswith(b"#") and not (name.endswith(YAML_SUFFIXES) and raw.startswith(b"---")):
        return
    head = raw.decode("utf-8", errors="replace")
    if "code" in kinds:   # first: a YAML file that does not load must not hide the anchor of its block
        _code_anchor(path, head, rel, found)
    if name.endswith(YAML_SUFFIXES) and "yaml" in kinds and path.stat().st_size <= DATA_MAX_BYTES:
        _yaml_file(path, rel, schemas, found)


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
        schema, recognizer = _typed_schema(path, decl, rel, schemas, found, report=False)
        if schema is not None:
            _schema_anchors(doc, schema, recognizer, path, rel, found)


def with_typed_anchors(index: FrontmatterIndex, found: TypedAnchors) -> FrontmatterIndex:
    """A copy of a Markdown index with the typed anchors added as targets. A uuid declared twice, by any two files
    or two elements, is ambiguous, as between two Markdown files; except that a `#---` block anchor gives way to a
    Markdown frontmatter with its uuid (a script and its README, a copied file): it is skipped, so a tree that was
    green before typed anchors existed stays green."""
    anchors = {p: [(e, u) for e, u in items
                   if (p, u) not in found.code or (u not in index.by_uuid and u not in index.duplicates)]
               for p, items in found.anchors.items()}
    merged = FrontmatterIndex(by_uuid=dict(index.by_uuid),
                              duplicates={u: list(ps) for u, ps in index.duplicates.items()},
                              invalid=list(index.invalid), out_of_root=list(index.out_of_root),
                              pointers=dict(index.pointers))
    for path, items in anchors.items():
        for element, u in items:
            if merged.by_uuid.get(u) == path and merged.pointers.get(u, "") == element:
                continue   # the same anchor declared twice by one file (a typed field and its block): one target
            merged.typed_anchors += 1
            if u in merged.duplicates:
                merged.duplicates[u].append(path)
            elif u in merged.by_uuid:
                merged.duplicates[u] = [merged.by_uuid.pop(u), path]
                merged.pointers.pop(u, None)
            else:
                merged.by_uuid[u] = path
                if element:
                    merged.pointers[u] = element
    return merged
