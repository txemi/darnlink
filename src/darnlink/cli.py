"""darnlink CLI. Default is a read-only report; `--write` applies.

    darnlink [PATH]                              # dry-run: what repair would do
    darnlink [PATH] --write                      # apply path repairs
    darnlink [PATH] --robustify [--write] [--create-frontmatter]
    darnlink [PATH] --robustify --create-frontmatter --no-create-frontmatter-for content.md
    darnlink [PATH] --exclude external_repos --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .frontmatter_index import DEFAULT_EXCLUDES, build_index
from .repair import apply_repairs, plan_repairs
from .report import Finding, Kind
from .robustify import apply_robustify, plan_robustify


def _findings_json(
    findings: List[Finding],
    wrote: int,
    write: bool,
    ignored: Optional[List[Path]] = None,
    invalid: Optional[List[Path]] = None,
    link_ignored: Optional[List[Path]] = None,
) -> str:
    return json.dumps(
        {
            "wrote": wrote,
            "applied": write,
            "ignored_files": [str(p) for p in (ignored or [])],
            # feature 006: opted out as a SOURCE only — still indexed as a target
            "link_ignored_files": [str(p) for p in (link_ignored or [])],
            "invalid_frontmatter_files": [str(p) for p in (invalid or [])],
            "findings": [{"kind": f.kind.value, "file": str(f.file), "detail": f.detail} for f in findings],
        },
        indent=2,
    )


def _run_repair(root: Path, write: bool, excludes: set, as_json: bool, block_markers: tuple) -> int:
    index = build_index(root, excludes)
    result = plan_repairs(root, index, excludes, block_markers)
    repairs = [f for f in result.findings if f.kind is Kind.REPAIR]
    conflicts = [f for f in result.findings if f.kind is Kind.CONFLICT]
    unresolved = [f for f in result.findings if f.kind in (Kind.UNRESOLVABLE, Kind.AMBIGUOUS)]
    wrote = len(apply_repairs(result)) if write else 0

    if as_json:
        print(_findings_json(result.findings, wrote, write, result.ignored, index.invalid,
                             result.link_ignored))
    else:
        print(f"darnlink repair — root: {root}")
        print(f"  indexed uuids: {len(index.by_uuid)} | duplicate uuids: {len(index.duplicates)}")
        print(f"  links to repair: {len(repairs)} | conflicts: {len(conflicts)} | unresolved: {len(unresolved)} | ignored files: {len(result.ignored)} | link-ignored: {len(result.link_ignored)} | invalid frontmatter: {len(index.invalid)}")
        for f in repairs:
            print(f"  [repair] {f.file}: {f.detail}")
        for f in conflicts:
            print(f"  [conflict] {f.file}: {f.detail}")
        for f in unresolved:
            print(f"  [{f.kind.value}] {f.file}: {f.detail}")
        for f in [x for x in result.findings if x.kind is Kind.IGNORED_LINKS]:
            print(f"  [link-ignored] {f.file}: {f.detail}")
        for p in index.invalid:
            print(f"  [invalid-frontmatter] {p}: not valid YAML; not indexed (fix the file)")
        if write:
            print(f"  WROTE {wrote} file(s).")
        elif repairs:
            print("  (dry-run — nothing written. Re-run with --write to apply.)")

    return 1 if conflicts or unresolved or index.invalid or (repairs and not write) else 0


def _run_robustify(root: Path, write: bool, create_frontmatter: bool, excludes: set, as_json: bool, block_markers: tuple, no_create_globs: tuple) -> int:
    result = plan_robustify(root, create_frontmatter=create_frontmatter, excludes=excludes, block_markers=block_markers, no_create_globs=no_create_globs)
    upgrades = [f for f in result.findings if f.kind is Kind.ROBUSTIFY]
    skipped = [f for f in result.findings if f.kind is Kind.NO_FRONTMATTER]
    denied = [f for f in result.findings if f.kind is Kind.DENY_LISTED]
    wrote = len(apply_robustify(result)) if write else 0

    if as_json:
        print(_findings_json(result.findings, wrote, write, result.ignored, result.invalid,
                             result.link_ignored))
    else:
        print(f"darnlink robustify — root: {root}")
        print(f"  plain links to robustify: {len(upgrades)} | skipped (no frontmatter): {len(skipped)} | deny-listed: {len(denied)} | ignored files: {len(result.ignored)} | link-ignored: {len(result.link_ignored)} | invalid frontmatter: {len(result.invalid)}")
        for f in upgrades:
            print(f"  [robustify] {f.file}: {f.detail}")
        for f in skipped:
            print(f"  [no-frontmatter] {f.file}: {f.detail} (use --create-frontmatter to allow)")
        for f in denied:
            print(f"  [deny-listed] {f.file}: {f.detail}")
        for f in [x for x in result.findings if x.kind is Kind.IGNORED_LINKS]:
            print(f"  [link-ignored] {f.file}: {f.detail}")
        for p in result.invalid:
            print(f"  [invalid-frontmatter] {p}: not valid YAML; left untouched (fix the file)")
        if write:
            print(f"  WROTE {wrote} file(s).")
        elif upgrades:
            print("  (dry-run — nothing written. Re-run with --write to apply.)")

    return 1 if result.invalid or (upgrades and not write) else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="darnlink",
        description="auto-healing Markdown links: repair links whose target moved, "
        "or robustify plain links (anchored by UUID).",
    )
    parser.add_argument("path", nargs="?", default=".", help="root directory to scan (default: .)")
    parser.add_argument("--write", action="store_true", help="apply changes (default: dry-run report)")
    parser.add_argument("--robustify", action="store_true", help="upgrade plain links to robust (default op: repair)")
    parser.add_argument("--create-frontmatter", action="store_true", help="(robustify) allow creating frontmatter where missing")
    parser.add_argument(
        "--no-create-frontmatter-for",
        action="append",
        default=[],
        metavar="GLOB",
        help="(robustify) basename glob whose targets are never given a uuid — no frontmatter block "
        "created and no uuid line inserted into existing frontmatter — regardless of "
        "--create-frontmatter (repeatable; e.g. --no-create-frontmatter-for content.md). For files a "
        "pipeline regenerates. Reusing a uuid the target already has is unaffected.",
    )
    parser.add_argument("--exclude", action="append", default=[], metavar="NAME", help="directory name to skip (repeatable)")
    parser.add_argument(
        "--ignore-block",
        action="append",
        default=[],
        metavar="NAME",
        help="ignore links inside generated blocks <!-- NAME-start --> ... <!-- NAME-end --> "
        "(repeatable; e.g. --ignore-block autogrid)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    excludes = set(DEFAULT_EXCLUDES) | set(args.exclude)
    block_markers = tuple(args.ignore_block)
    if args.robustify:
        return _run_robustify(
            root, args.write, args.create_frontmatter, excludes, args.json, block_markers,
            tuple(args.no_create_frontmatter_for),
        )
    return _run_repair(root, args.write, excludes, args.json, block_markers)


if __name__ == "__main__":
    sys.exit(main())
