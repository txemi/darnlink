"""Robustify: upgrade a plain relative link to a robust one.

For each plain link that resolves to a local `.md` file — or to a *directory* (feature 011), which is
anchored to its `README.md` — ensure that target has a `uuid` in its frontmatter (reuse it, or create
one because a link now references it), then append the `<!-- uuid: … -->` annotation to the link. A
UUID is created only where a link needs it. A directory with no `README.md` is not anchorable and its
link is left plain (darnlink never creates a README).

Targets without any frontmatter are skipped unless `create_frontmatter=True` (Constitution II:
creating frontmatter is opt-in).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .frontmatter_edit import (
    add_uuid_to_content,
    new_uuid,
    read_text_keep_newlines,
    write_text_keep_newlines,
)
from .frontmatter_index import DEFAULT_EXCLUDES, iter_markdown_files, read_frontmatter_uuid
from .links import (code_spans, emit_robust_link, file_ignores_links, file_is_ignored,
                    find_plain_links, ignored_spans)
from .paths import DIR_ANCHOR, is_local_relative, names_md, resolve_href
from .report import Finding, Kind
from .scope import in_scope


@dataclass
class RobustifyResult:
    findings: List[Finding] = field(default_factory=list)
    new_content: Dict[Path, str] = field(default_factory=dict)
    ignored: List[Path] = field(default_factory=list)  # files skipped via the ignore-file marker
    link_ignored: List[Path] = field(default_factory=list)  # sources via the ignore-links marker (006)
    invalid: List[Path] = field(default_factory=list)  # files with non-YAML frontmatter (reported)
    suppressed: int = 0  # anchorable links in files outside the write scope (010): counted, never hidden


def _anchor_target(href: str, linking_file: Path) -> Path | None:
    """The `.md` file whose `uuid` anchors this link, or None.

    - A link to a `.md` file anchors to that file (the original behavior).
    - A link to a *directory* anchors to that directory's `README.md` (feature 011): a folder's
      identity is its README's uuid. A directory with no README is not anchorable — it returns None,
      exactly like any other non-`.md` target, so the link is left plain.
    """
    if not is_local_relative(href):
        return None
    t = resolve_href(href, linking_file)
    if names_md(href):
        # is_file() (not exists()): a *directory* named `foo.md` exists with a `.md` suffix but is
        # not an anchor — treating it as one would fail the later frontmatter read/write.
        return t if (t.is_file() and t.suffix.lower() == ".md") else None
    if t.is_dir():
        readme = t / DIR_ANCHOR
        if readme.is_file():  # a directory named `README.md` is not an anchor either
            return readme
    return None


def _basename_denied(target: Path, no_create_globs: Tuple[str, ...]) -> bool:
    """True if the target's basename matches any deny-list glob (FR-029/FR-032)."""
    return any(fnmatch(target.name, g) for g in no_create_globs)


def plan_robustify(
    root: Path,
    create_frontmatter: bool = False,
    excludes: set = DEFAULT_EXCLUDES,
    block_markers: tuple = (),
    no_create_globs: Tuple[str, ...] = (),
    only: Optional[Set[Path]] = None,
    allow_target_writes: bool = True,
) -> RobustifyResult:
    """Plan the robustify pass over `root` (no writes).

    `only` (feature 010) narrows the **write** scope, never the scan: the whole tree is still read,
    because a link's target — whose `uuid` this pass needs — usually lives outside the caller's own
    subtree. Only links inside the named files are annotated; anchorable links elsewhere are counted
    in `suppressed`.

    `allow_target_writes=False` refuses the one write that legitimately lands outside `only`: adding
    a `uuid` to a *target* so the link can be anchored at all (FR-006). Such links stay plain and are
    reported.
    """
    result = RobustifyResult()
    link_ignored: Set[Path] = set()   # feature 006: sources that opt their own links out
    contents: Dict[Path, str] = {}
    spans: Dict[Path, list] = {}
    files: List[Path] = []
    for f in iter_markdown_files(root, excludes):
        try:
            c = read_text_keep_newlines(f)
        except Exception:
            continue
        if file_is_ignored(c):
            result.ignored.append(f)  # not a source and (being absent from contents) not a target
            continue
        # Feature 006: source-only opt-out. It stays in `files`/`contents` on purpose — it must still
        # be able to RECEIVE its own uuid as a target (FR-035), and that write lives in the Phase B
        # loop. Only the link-rewriting halves (Phase A's decide, Phase B's annotate) skip it.
        files.append(f)
        contents[f] = c
        if file_ignores_links(c):
            link_ignored.add(f.resolve())
            continue  # no spans: nothing reads them for this file, and computing them re-parses it
        spans[f] = ignored_spans(c, block_markers) + code_spans(c)

    ignored_targets = {p.resolve() for p in result.ignored}  # opted-out files: never become targets

    # --- Phase A: decide the uuid for every target of a plain link ---
    target_uuid: Dict[Path, str] = {}   # target -> uuid to annotate with
    needs_uuid_write: Set[Path] = set() # targets we will add a uuid to
    skip_no_fm: Set[Path] = set()       # targets with no frontmatter and create disabled
    skip_denied: Set[Path] = set()      # targets matched by --no-create-frontmatter-for (never a uuid)
    invalid_fm: Set[Path] = set()       # targets whose frontmatter is not valid YAML (reported)
    skip_out_of_scope: Set[Path] = set()   # targets that exist but were never scanned (FR-009)
    skip_target_write: Set[Path] = set()   # targets needing a uuid, refused by --no-target-writes (FR-006)

    def decide(target: Path) -> None:
        target = target.resolve()
        if (target in target_uuid or target in skip_no_fm or target in skip_denied
                or target in invalid_fm or target in skip_out_of_scope or target in skip_target_write):
            return
        c = contents.get(target)
        if c is None:
            # FR-009: the target exists on disk but is outside the scanned root (or excluded), so its
            # frontmatter was never read. Reporting this as "no frontmatter" states as fact something
            # this run never checked — it is a *scope* result, and gets its own kind.
            skip_out_of_scope.add(target)
            return
        status, existing = read_frontmatter_uuid(c)  # canonical YAML reader (FR-023)
        if status == "invalid":
            invalid_fm.add(target)  # not valid YAML: never read, never written (FR-024)
            return
        if existing:
            target_uuid[target] = existing  # reuse is not creation: never gated by the deny-list
            return
        if _basename_denied(target, no_create_globs):
            # regenerated companion (a pipeline rewrites it): never give it a uuid — neither create
            # a block nor insert into an existing one (FR-029/FR-030). Tracked separately from
            # skip_no_fm so the report is accurate (it is not a "needs --create-frontmatter" case).
            skip_denied.add(target)
            return
        if not in_scope(target, only) and not allow_target_writes:
            # FR-006: anchoring this link would write a uuid into a file the caller did not name.
            # The caller asked for the hard guarantee, so the link stays plain and is reported.
            skip_target_write.add(target)
            return
        u = new_uuid()
        if add_uuid_to_content(c, u, create_frontmatter) is None:
            skip_no_fm.add(target)  # no frontmatter, creation not allowed
            return
        target_uuid[target] = u
        needs_uuid_write.add(target)

    for f in files:
        if f.resolve() in link_ignored:
            continue  # FR-033: its links are never rewritten -> they must not drive uuid creation
        if not in_scope(f, only):
            continue  # 010: its links are never rewritten either -> they must not create uuids
        for link in find_plain_links(contents.get(f, ""), spans.get(f, [])):
            t = _anchor_target(link.href, f)
            # Skip self-links (a file linking to itself, e.g. autogrid `path` rows): robustifying
            # them is meaningless and would touch machine-generated blocks.
            if t is not None and t.resolve() != f.resolve():
                decide(t)

    # --- Phase A′ (only when narrowed): count what a full run would have anchored elsewhere ---
    # Constitution II — no silent caps: a narrowed run must not read like a clean tree. Only links
    # whose target ALREADY has a uuid are counted; deciding the rest would mean minting uuids for
    # files this run has no mandate to touch.
    if only is not None:
        has_uuid: Dict[Path, bool] = {}  # target -> already has a uuid; parse each target once (Copilot)

        def _target_has_uuid(tr: Path) -> bool:
            cached = has_uuid.get(tr)
            if cached is None:
                c = contents.get(tr)
                status, existing = read_frontmatter_uuid(c) if c is not None else ("none", None)
                cached = status == "valid" and bool(existing)
                has_uuid[tr] = cached
            return cached

        for f in files:
            if in_scope(f, only) or f.resolve() in link_ignored:
                continue
            for link in find_plain_links(contents.get(f, ""), spans.get(f, [])):
                t = _anchor_target(link.href, f)
                if t is None or t.resolve() == f.resolve():
                    continue
                tr = t.resolve()
                if tr in ignored_targets or tr not in contents:
                    continue
                if _target_has_uuid(tr):
                    result.suppressed += 1

    # --- Phase B: per file, annotate plain links, then add its own uuid if it is a target ---
    for f in files:
        original = contents.get(f, "")
        pieces: List[str] = []
        cursor = 0
        changed = False
        scoped = in_scope(f, only)  # 010: may this file's own links be rewritten?
        if f.resolve() in link_ignored:
            # FR-033: leave every link in it alone. We still fall through to the uuid write below,
            # because opting out as a SOURCE says nothing about being a target (FR-034/FR-035).
            result.link_ignored.append(f)
            if scoped:
                result.findings.append(Finding(
                    Kind.IGNORED_LINKS, f,
                    "file carries darnlink-ignore-links; its links are left as-is (still a target)"))
        # Out of the write scope: its links are left alone here too, but it may still RECEIVE its own
        # uuid below — being a target is not a write the caller has to name (FR-006).
        links = () if (f.resolve() in link_ignored or not scoped) else find_plain_links(original, spans.get(f, []))
        for link in links:
            t = _anchor_target(link.href, f)
            if t is None or t.resolve() == f.resolve():
                continue  # skip non-md/external and self-links
            tr = t.resolve()
            if tr in ignored_targets or tr in invalid_fm:
                continue  # opted-out or invalid-YAML target: leave the link plain (invalid reported below)
            if tr in skip_denied:
                result.findings.append(
                    Finding(Kind.DENY_LISTED, f, f"{link.href}: target deny-listed (--no-create-frontmatter-for); link left plain")
                )
                continue
            if tr in skip_out_of_scope:
                result.findings.append(
                    Finding(Kind.OUT_OF_SCOPE, f,
                            f"{link.href}: target is outside the scanned root (or skipped by "
                            f"--exclude); its uuid was never read — scan the target (widen PATH "
                            f"or drop the --exclude that hides it) to anchor this link")
                )
                continue
            if tr in skip_target_write:
                result.findings.append(
                    Finding(Kind.TARGET_WRITE_REFUSED, f,
                            f"{link.href}: target needs a uuid but is outside --only and "
                            f"--no-target-writes is set; link left plain")
                )
                continue
            if tr in skip_no_fm:
                result.findings.append(
                    Finding(Kind.NO_FRONTMATTER, f, f"{link.href}: target has no frontmatter; skipped")
                )
                continue
            u = target_uuid.get(tr)
            if u is None:
                continue
            pieces.append(original[cursor:link.start])
            pieces.append(emit_robust_link(link.text, link.href, u))
            cursor = link.end
            changed = True
            result.findings.append(Finding(Kind.ROBUSTIFY, f, f"{link.href} +uuid {u}"))
        content = ("".join(pieces) + original[cursor:]) if changed else original

        if f.resolve() in needs_uuid_write:
            added = add_uuid_to_content(content, target_uuid[f.resolve()], create_frontmatter)
            if added is not None:
                content = added

        if content != original:
            result.new_content[f] = content

    # FR-006: name every uuid write that lands OUTSIDE the write scope — in the dry-run report too,
    # so the caller sees it before it happens and can refuse it with --no-target-writes.
    if only is not None:
        for t in sorted(needs_uuid_write):
            if not in_scope(t, only):
                result.findings.append(Finding(
                    Kind.TARGET_UUID_WRITE, t,
                    "uuid added to this target (outside --only) so an inbound link could be anchored"))

    # report invalid-frontmatter targets once each (never read, never written) — FR-024/FR-026
    for p in sorted(invalid_fm):
        result.invalid.append(p)
        result.findings.append(Finding(Kind.INVALID_FRONTMATTER, p, "frontmatter is not valid YAML; left untouched"))
    return result


def apply_robustify(result: RobustifyResult) -> List[Path]:
    written: List[Path] = []
    for path, content in result.new_content.items():
        write_text_keep_newlines(path, content)
        written.append(path)
    return written
