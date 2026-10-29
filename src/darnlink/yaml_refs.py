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

The targets are the frontmatter `uuid` of every `.md` file (the same index as the Markdown links) and
the top-level `uuid` of every YAML file. Each reference is then judged like a robust Markdown link:
correct, repairable (the uuid lives elsewhere: the new relative path is proposed, and written with
`--write`), conflicting (the path still names an existing file that is not the uuid's), unresolvable
or ambiguous. A `link` that is a web URL is not checked here (a `DarnlinkWebRef` may point to
another repository).

Known limits: a `$ref` to another file (other than the reference type itself), `prefixItems`, `if` and
`not` are not followed, and a repeated `link` key is not reported (the YAML loader keeps the last one).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .frontmatter_index import DEFAULT_EXCLUDES, build_index, dir_excluded
from .paths import is_web_href, relative_link, resolve_href, resolved, split_fragment

REF_DEF_NAME = "DarnlinkRef"
REF_SCHEMA_FILE = "ref.schema.json"
YAML_SUFFIXES = (".yaml", ".yml")
MAX_DEPTH = 64

_MODELINE = re.compile(r"^#\s*yaml-language-server:\s*\$schema=(\S+)")

OK, REPAIR, CONFLICT, UNRESOLVABLE, AMBIGUOUS, MALFORMED, NO_SCHEMA, UNREADABLE = (
    "ok", "repair", "conflict", "unresolvable", "ambiguous", "malformed", "unreadable-schema", "unreadable-yaml")

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


def _matches(pattern: object, key: str) -> bool:
    """`re.search`, tolerant of a pattern Python cannot compile (JSON Schema regexes are ECMA-262)."""
    try:
        return isinstance(pattern, str) and re.search(pattern, key) is not None
    except re.error:
        return False


def ref_positions(instance: object, schema: dict) -> List[Tuple[str, object]]:
    """[(JSON Pointer, value)] of every position of `instance` whose schema node is the reference type.
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
        if is_ref_type(ref):
            if not alternative or (isinstance(value, dict) and (
                    "link" in value or ("uuid" in value and alternative == "lone"))):
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


def mentions_ref_type(schema: object, depth: int = 0) -> bool:
    """True if some `$ref` anywhere in the schema names the reference type. A schema without one declares no
    reference, so its YAML files need not even load."""
    if depth > MAX_DEPTH:
        return False
    if isinstance(schema, dict):
        return is_ref_type(schema.get("$ref")) or any(mentions_ref_type(v, depth + 1) for v in schema.values())
    if isinstance(schema, list):
        return any(mentions_ref_type(v, depth + 1) for v in schema)
    return False


@dataclass
class TargetIndex:
    """uuid -> file, over `.md` frontmatter and YAML top-level `uuid`. A uuid in two files is ambiguous."""
    by_uuid: Dict[str, Path]
    duplicates: Dict[str, List[Path]]

    def get(self, uuid: str) -> Optional[Path]:
        return self.by_uuid.get(uuid.lower())

    def is_ambiguous(self, uuid: str) -> bool:
        return uuid.lower() in self.duplicates


def build_target_index(root: Path, excludes: set[str], yaml_docs: Dict[Path, object]) -> TargetIndex:
    md = build_index(root, excludes)
    by_uuid = dict(md.by_uuid)
    duplicates = {u: list(ps) for u, ps in md.duplicates.items()}
    for path, doc in yaml_docs.items():
        u = doc.get("uuid") if isinstance(doc, dict) else None
        if not isinstance(u, str) or not u.strip():
            continue
        u = u.strip().lower()
        if u in duplicates:
            duplicates[u].append(path)
        elif u in by_uuid:
            duplicates[u] = [by_uuid.pop(u), path]
        else:
            by_uuid[u] = path
    return TargetIndex(by_uuid, duplicates)


def _shown(path: Path, root: Path) -> str:
    try:
        return resolved(path).relative_to(resolved(root)).as_posix()
    except ValueError:
        return path.as_posix()


def _same(a: Path, b: Path) -> bool:
    return resolved(a) == resolved(b)


def judge(value: object, yaml_file: Path, index: TargetIndex, root: Path) -> Tuple[str, str, str, str, str]:
    """(kind, link, uuid, detail, new_link) for one reference value. `root` only shortens the paths in `detail`."""
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
    if _same(points, target):
        return OK, link, uuid, "", ""
    if points.is_file():
        return CONFLICT, link, uuid, f"path names an existing file, but the uuid lives in {shown}", ""
    return REPAIR, link, uuid, f"target moved to {shown}", relative_link(target, yaml_file, split_fragment(link)[1])


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
    index = build_target_index(root, excludes, docs)
    schemas: Dict[Path, Optional[dict]] = {}
    typed: Dict[Path, bool] = {}
    stats = {"yaml_files": len(files), "with_schema": 0, "references": 0, "ok": 0}
    findings: List[RefFinding] = []
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
        if spath not in typed:
            typed[spath] = mentions_ref_type(schema)
        if not typed[spath]:
            continue
        if docs[path] is UNREADABLE_DOC:
            findings.append(RefFinding(UNREADABLE, rel, "/", "", "", "the file has a schema modeline but does not "
                                                                         "load as one YAML document"))
            continue
        stats["with_schema"] += 1
        for pointer, value in ref_positions(docs[path], schema):
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
    if args.write:
        by_file: Dict[str, List[RefFinding]] = {}
        for f in findings:
            if f.kind == REPAIR:
                by_file.setdefault(f.file, []).append(f)
        for rel, items in by_file.items():
            left = apply_repairs(root.resolve() / rel, items)
            repaired += [f for f in items if f not in left]
        findings = [f for f in findings if f not in repaired]
    if args.json:
        print(json.dumps({"stats": stats, "findings": [asdict(f) for f in findings],
                          "repaired": [asdict(f) for f in repaired]}, ensure_ascii=False, indent=2))
    else:
        for f in repaired:
            print(f"REPAIRED     {f.file}#{f.pointer}  {f.link} -> {f.new_link}")
        for f in findings:
            extra = f"  -> {f.new_link}" if f.new_link else ""
            print(f"{f.kind.upper():<12} {f.file}#{f.pointer}  {f.link}  ({f.detail}){extra}")
        print(f"darnlink yaml-refs: {stats['references']} references in {stats['with_schema']} YAML files with a "
              f"local schema ({stats['yaml_files']} scanned): {stats['ok']} ok, {len(repaired)} repaired, "
              f"{len(findings)} broken")
    return 2 if findings else 0
