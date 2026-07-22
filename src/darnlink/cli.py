"""darnlink CLI. Default is a read-only report; `--write` applies.

    darnlink [PATH]                              # dry-run: what repair would do
    darnlink [PATH] --write                      # apply path repairs
    darnlink [PATH] --robustify [--write] [--create-frontmatter]
    darnlink [PATH] --robustify --create-frontmatter --no-create-frontmatter-for content.md
    darnlink [PATH] --exclude external_repos --json
    darnlink [PATH] --robustify --write --only sub/dir/A.md   # scan PATH, write only A.md
    git diff --cached --name-only -- '*.md' | darnlink . --robustify --write --only-from -
    darnlink check [PATH]                        # report-only gate: BOTH checks, exit 0/2/3 (1 on usage)
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
from .scope import ScopeError, read_paths_from, resolve_write_scope


def _scope_note(suppressed: int) -> str:
    return (f"  NOTE: {suppressed} finding(s) in files outside --only were neither written nor "
            f"listed (drop --only to see them).")


def _findings_json(
    findings: List[Finding],
    wrote: int,
    write: bool,
    ignored: Optional[List[Path]] = None,
    invalid: Optional[List[Path]] = None,
    link_ignored: Optional[List[Path]] = None,
    suppressed: int = 0,
    only: Optional[set] = None,
) -> str:
    return json.dumps(
        {
            "wrote": wrote,
            "applied": write,
            "write_scope": sorted(str(p) for p in only) if only is not None else None,
            "suppressed_outside_write_scope": suppressed,
            "ignored_files": [str(p) for p in (ignored or [])],
            # feature 006: opted out as a SOURCE only — still indexed as a target
            "link_ignored_files": [str(p) for p in (link_ignored or [])],
            "invalid_frontmatter_files": [str(p) for p in (invalid or [])],
            "findings": [{"kind": f.kind.value, "file": str(f.file), "detail": f.detail} for f in findings],
        },
        indent=2,
    )


def _run_repair(root: Path, write: bool, excludes: set, as_json: bool, block_markers: tuple,
                only: Optional[set] = None) -> int:
    index = build_index(root, excludes)
    result = plan_repairs(root, index, excludes, block_markers, only=only)
    repairs = [f for f in result.findings if f.kind is Kind.REPAIR]
    conflicts = [f for f in result.findings if f.kind is Kind.CONFLICT]
    unresolved = [f for f in result.findings if f.kind in (Kind.UNRESOLVABLE, Kind.AMBIGUOUS)]
    wrote = len(apply_repairs(result)) if write else 0

    if as_json:
        print(_findings_json(result.findings, wrote, write, result.ignored, index.invalid,
                             result.link_ignored, result.suppressed, only))
    else:
        print(f"darnlink repair — root: {root}")
        if only is not None:
            print(f"  write scope: {len(only)} file(s) (--only)")
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
        if only is not None:
            # FR-008: a narrowed run only ever sees the links written INSIDE the scoped files. A moved
            # target's inbound links live in files the caller did not name — a clean result here is
            # not evidence of a clean tree, and must not read like one.
            print("  NOTE: --only checks outbound links of the scoped files; a moved target's "
                  "inbound links still need a full-tree run.")
            if result.suppressed:
                print(_scope_note(result.suppressed))
        if write:
            print(f"  WROTE {wrote} file(s).")
        elif repairs:
            print("  (dry-run — nothing written. Re-run with --write to apply.)")

    return 1 if conflicts or unresolved or index.invalid or (repairs and not write) else 0


def _run_robustify(root: Path, write: bool, create_frontmatter: bool, excludes: set, as_json: bool, block_markers: tuple, no_create_globs: tuple, only: Optional[set] = None, allow_target_writes: bool = True, create_readme: bool = False) -> int:
    result = plan_robustify(root, create_frontmatter=create_frontmatter, excludes=excludes, block_markers=block_markers, no_create_globs=no_create_globs, only=only, allow_target_writes=allow_target_writes, create_readme=create_readme)
    upgrades = [f for f in result.findings if f.kind is Kind.ROBUSTIFY]
    created_readmes = [f for f in result.findings if f.kind is Kind.CREATE_README]
    skipped = [f for f in result.findings if f.kind is Kind.NO_FRONTMATTER]
    denied = [f for f in result.findings if f.kind is Kind.DENY_LISTED]
    out_of_scope = [f for f in result.findings if f.kind is Kind.OUT_OF_SCOPE]
    target_writes = [f for f in result.findings if f.kind is Kind.TARGET_UUID_WRITE]
    refused = [f for f in result.findings if f.kind is Kind.TARGET_WRITE_REFUSED]
    wrote = len(apply_robustify(result)) if write else 0

    if as_json:
        print(_findings_json(result.findings, wrote, write, result.ignored, result.invalid,
                             result.link_ignored, result.suppressed, only))
    else:
        print(f"darnlink robustify — root: {root}")
        if only is not None:
            print(f"  write scope: {len(only)} file(s) (--only)")
        print(f"  plain links to robustify: {len(upgrades)} | skipped (no frontmatter): {len(skipped)} | out of scanned root: {len(out_of_scope)} | deny-listed: {len(denied)} | ignored files: {len(result.ignored)} | link-ignored: {len(result.link_ignored)} | invalid frontmatter: {len(result.invalid)}")
        for f in upgrades:
            print(f"  [robustify] {f.file}: {f.detail}")
        for f in created_readmes:
            print(f"  [create-readme] {f.file}: {f.detail}")
        for f in skipped:
            print(f"  [no-frontmatter] {f.file}: {f.detail} (use --create-frontmatter to allow)")
        for f in out_of_scope:
            print(f"  [out-of-scope] {f.file}: {f.detail}")
        for f in target_writes:
            print(f"  [target-uuid-write] {f.file}: {f.detail}")
        for f in refused:
            print(f"  [target-write-refused] {f.file}: {f.detail}")
        for f in denied:
            print(f"  [deny-listed] {f.file}: {f.detail}")
        for f in [x for x in result.findings if x.kind is Kind.IGNORED_LINKS]:
            print(f"  [link-ignored] {f.file}: {f.detail}")
        for p in result.invalid:
            print(f"  [invalid-frontmatter] {p}: not valid YAML; left untouched (fix the file)")
        if only is not None and result.suppressed:
            print(_scope_note(result.suppressed))
        if write:
            print(f"  WROTE {wrote} file(s).")
        elif result.new_content:
            print("  (dry-run — nothing written. Re-run with --write to apply.)")

    # Any planned write (a robustified link, a created README, a target uuid) is a pending change: the
    # dry-run gate must exit non-zero for all of them, not just ROBUSTIFY — otherwise a --create-readme
    # run with no plain-link upgrades would report 0 despite files waiting to be written.
    return 1 if result.invalid or (result.new_content and not write) else 0


def _run_check(root: Path, excludes: set, as_json: bool, block_markers: tuple,
               only: Optional[set] = None) -> int:
    """Feature 007: report-only gate. Run BOTH checks (integrity + strict) in one invocation and
    return a distinguishable exit code. Never writes. `--robustify` alone does not catch a broken
    robust link, and plain `darnlink .` does not catch an un-anchored plain link — a gate that runs
    only one is blind to the other; `check` runs both so a consumer cannot forget a half.

    Exit: 0 clean · 2 integrity failure (broken/unresolvable robust links or invalid frontmatter) ·
    3 strict-only failure (anchorable plain links un-anchored). Integrity takes precedence over
    strict when both fail (a broken link is more urgent than an un-anchored one).
    """
    # Integrity axis (repair, dry-run): robust links whose path is stale/unresolvable, plus invalid YAML.
    # FR-010: `--only` restricts FINDINGS to links whose source file is in the set (check writes
    # nothing, so there is no write scope — just a report filter). The index is still whole.
    index = build_index(root, excludes)
    rep = plan_repairs(root, index, excludes, block_markers, only=only)
    repairs = [f for f in rep.findings if f.kind is Kind.REPAIR]
    conflicts = [f for f in rep.findings if f.kind is Kind.CONFLICT]
    unresolved = [f for f in rep.findings if f.kind in (Kind.UNRESOLVABLE, Kind.AMBIGUOUS)]
    # Invalid frontmatter is a file-level integrity fault; when scoped, only the caller's own files
    # count — a gate must not fail my commit over someone else's un-staged invalid YAML.
    invalid = [p for p in index.invalid if only is None or p.resolve() in only]
    integrity_fail = bool(repairs or conflicts or unresolved or invalid)

    # Strict axis (robustify, dry-run): plain links to an anchorable target left un-anchored.
    rob = plan_robustify(root, create_frontmatter=False, excludes=excludes, block_markers=block_markers, only=only)
    upgrades = [f for f in rob.findings if f.kind is Kind.ROBUSTIFY]
    rob_invalid = [p for p in rob.invalid if only is None or p.resolve() in only]
    strict_fail = bool(upgrades or rob_invalid)

    code = 2 if integrity_fail else (3 if strict_fail else 0)

    if as_json:
        print(json.dumps({
            "check": True,
            "exit_code": code,
            "write_scope": sorted(str(p) for p in only) if only is not None else None,
            "integrity": {
                "failed": integrity_fail,
                "repairs": len(repairs), "conflicts": len(conflicts),
                "unresolved": len(unresolved), "invalid_frontmatter": len(invalid),
                "invalid_frontmatter_files": [str(p) for p in invalid],
                "findings": [{"kind": f.kind.value, "file": str(f.file), "detail": f.detail}
                             for f in (repairs + conflicts + unresolved)]
                + [{"kind": Kind.INVALID_FRONTMATTER.value, "file": str(p),
                    "detail": "frontmatter present but not valid YAML; not indexed"}
                   for p in invalid],
            },
            "strict": {
                "failed": strict_fail,
                "robustify": len(upgrades), "invalid_frontmatter": len(rob_invalid),
                "invalid_frontmatter_files": [str(p) for p in rob_invalid],
                "findings": [{"kind": f.kind.value, "file": str(f.file), "detail": f.detail}
                             for f in upgrades]
                + [{"kind": Kind.INVALID_FRONTMATTER.value, "file": str(p),
                    "detail": "frontmatter present but not valid YAML; left untouched (fix the file)"}
                   for p in rob_invalid],
            },
        }, indent=2))
    else:
        outcome = {0: "clean", 2: "integrity failure", 3: "strict failure"}[code]
        print(f"darnlink check — root: {root}")
        if only is not None:
            print(f"  scope: {len(only)} file(s) (--only) — findings limited to their own links")
        print(f"  [integrity] repair: {len(repairs)} | conflicts: {len(conflicts)} | "
              f"unresolved: {len(unresolved)} | invalid frontmatter: {len(invalid)} "
              f"→ {'FAIL' if integrity_fail else 'ok'}")
        print(f"  [strict]    to robustify: {len(upgrades)} | invalid frontmatter: {len(rob_invalid)} "
              f"→ {'FAIL' if strict_fail else 'ok'}")
        for f in repairs + conflicts + unresolved:
            print(f"  [integrity/{f.kind.value}] {f.file}: {f.detail}")
        for p in invalid:
            print(f"  [integrity/invalid-frontmatter] {p}: not valid YAML; not indexed (fix the file)")
        for f in upgrades:
            print(f"  [strict/robustify] {f.file}: {f.detail}")
        for p in rob_invalid:
            print(f"  [strict/invalid-frontmatter] {p}: not valid YAML; left untouched (fix the file)")
        print(f"  → exit {code} ({outcome})")

    return code


class _CheckArgParser(argparse.ArgumentParser):
    # Exit 1 (usage) on a bad flag/arg, not argparse's default 2 — 2 means "integrity failure" here.
    def error(self, message: str):  # noqa: D401
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _run_check_cli(argv: List[str]) -> int:
    """Parse `darnlink check [PATH] [--exclude … --ignore-block … --json]` (report-only: no --write)."""
    parser = _CheckArgParser(
        prog="darnlink check",
        description="report-only gate: run BOTH the repair (integrity) and robustify (strict) checks "
        "over PATH and exit 0 (clean) / 2 (integrity) / 3 (strict). Never writes.",
    )
    parser.add_argument("path", nargs="?", default=".", help="root directory to scan (default: .)")
    parser.add_argument("--exclude", action="append", default=[], metavar="PATTERN", help="directory-name glob to skip (fnmatch, case-sensitive; a plain name matches exactly) (repeatable)")
    parser.add_argument("--ignore-block", action="append", default=[], metavar="NAME",
                        help="ignore links inside <!-- NAME-start --> … <!-- NAME-end --> blocks (repeatable)")
    parser.add_argument("--only", action="append", default=[], metavar="FILE",
                        help="(feature 010) limit findings to links whose SOURCE file is one of these .md "
                        "files (repeatable). The tree is still scanned in full; this is a report filter. "
                        "What a pre-commit gate needs: 'is what I am committing clean?'")
    parser.add_argument("--only-from", metavar="FILE",
                        help="read --only paths from FILE, one per line ('-' = stdin). Combines with --only.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 1
    only_paths = list(args.only)
    if args.only_from:
        try:
            only_paths += read_paths_from(args.only_from)
        except ScopeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    try:
        only = resolve_write_scope(only_paths, root)
    except ScopeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    excludes = set(DEFAULT_EXCLUDES) | set(args.exclude)
    return _run_check(root, excludes, args.json, tuple(args.ignore_block), only=only)


def main(argv: Optional[List[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "check":  # feature 007: report-only gate subcommand
        return _run_check_cli(raw[1:])

    parser = argparse.ArgumentParser(
        prog="darnlink",
        description="auto-healing Markdown links: repair links whose target moved, "
        "or robustify plain links (anchored by UUID).",
    )
    parser.add_argument("path", nargs="?", default=".", help="root directory to scan (default: .)")
    parser.add_argument("--write", action="store_true", help="apply changes (default: dry-run report)")
    parser.add_argument("--robustify", action="store_true", help="upgrade plain links to robust (default op: repair)")
    parser.add_argument("--create-frontmatter", action="store_true", help="(robustify) allow creating frontmatter where missing")
    parser.add_argument("--create-readme", action="store_true", help="(robustify, feature 012) for a link to a directory that has no README.md, create one (with a uuid) so the link can be anchored. Implies --create-frontmatter. darnlink never creates the directory, only a README inside an existing one.")
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
    parser.add_argument("--exclude", action="append", default=[], metavar="PATTERN", help="directory-name glob to skip (fnmatch, case-sensitive; a plain name matches exactly) (repeatable)")
    parser.add_argument(
        "--ignore-block",
        action="append",
        default=[],
        metavar="NAME",
        help="ignore links inside generated blocks <!-- NAME-start --> ... <!-- NAME-end --> "
        "(repeatable; e.g. --ignore-block autogrid)",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="FILE",
        help="(feature 010) restrict WRITES to these .md files — the tree is still scanned and indexed "
        "in full, only these are modified (repeatable). A target outside the set may still receive a "
        "uuid so a link can be anchored (see --no-target-writes).",
    )
    parser.add_argument(
        "--only-from",
        metavar="FILE",
        help="read --only paths from FILE, one per line ('-' = stdin). Combines with --only. Lets a "
        "caller pipe a generated list (e.g. `git diff --cached --name-only`) without darnlink knowing "
        "about git.",
    )
    parser.add_argument(
        "--no-target-writes",
        action="store_true",
        help="(with --only) never write a uuid into a target outside the write scope: such links are "
        "left plain and reported, guaranteeing NO file outside --only is modified.",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    only_paths = list(args.only)
    if args.only_from:
        try:
            only_paths += read_paths_from(args.only_from)
        except ScopeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.no_target_writes and not only_paths:
        print("error: --no-target-writes has no effect without --only/--only-from", file=sys.stderr)
        return 1
    try:
        only = resolve_write_scope(only_paths, root)
    except ScopeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    excludes = set(DEFAULT_EXCLUDES) | set(args.exclude)
    block_markers = tuple(args.ignore_block)
    if args.robustify:
        return _run_robustify(
            root, args.write, args.create_frontmatter,  # --create-readme implies it inside plan_robustify
            excludes, args.json, block_markers,
            tuple(args.no_create_frontmatter_for), only=only,
            allow_target_writes=not args.no_target_writes,
            create_readme=args.create_readme,
        )
    return _run_repair(root, args.write, excludes, args.json, block_markers, only=only)


if __name__ == "__main__":
    sys.exit(main())
