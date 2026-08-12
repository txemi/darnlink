#!/usr/bin/env python3
"""Ratchet gate: code and comments must be in ENGLISH.

WHY THIS EXISTS. This file is vendored VERBATIM into every repo that runs the gate, so it carries
no repo-specific text: each repo states its own reason next to its own wiring (the pre-commit
fragment and the CI workflow). The shared reason is that these repos port functionality between
each other, so a Spanish comment is a translation cost paid on *every* port, not cosmetic debt
that dies with the repo.

WHY A RATCHET AND NOT FAIL-CLOSED. A repo that adopts the rule late already carries offending
lines -- the first one to do so had ~1300 across 172 files, accumulated because the rule had never
been written down. Demanding they all be translated before the next commit would simply get the
gate deleted. So, following the owner's standing norm ("a repo's strictness only ever goes up,
never down") and the mechanism the consumer monorepo's `entity-structure` gate already
uses: legacy lines sit in
a baseline whose count can only DECREASE, while new or modified lines must be English from now on.
A repo that starts clean pins its baseline at 0, which is fail-closed with no extra machinery.

Two modes:

    lang_gate.py --diff [REF]     # pre-commit / PR: only ADDED lines (default REF: staged)
    lang_gate.py --baseline       # CI: whole tree; fails if the count GREW vs the baseline file
    lang_gate.py --update-baseline  # after translating: write the new (lower) count

The detector is deliberately a heuristic: Spanish function words plus accented characters, looked
for only in comments and docstrings. It cannot be exact -- `no`, `final` and `total` are valid in
both languages -- so a genuine false positive is silenced with a trailing `# lang-ok`.

Prior art was evaluated and rejected before writing this (2026-08-09): `flake8-only-english`
detects `ord(ch) > 127`, which misses a third of the Spanish in these repos because a third of it
carries no accents; `pybadcomments` does not import as published; pylint's spelling checker needs
the native `enchant` library, which is exactly the kind of dependency that turns a local gate into
a silent no-op on an unprovisioned machine. None of the three has a ratchet.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# Spanish function words that are NOT also common English words -- nor common code identifiers.
# `no`, `final`, `total`, `real`, `error`, `base` and friends are deliberately absent: they are
# identical in both languages and would fire on nearly every English comment, which is how a gate
# earns its way into `--no-verify`.
#
# `sin` was dropped for the same reason, but only after measuring (2026-08-09): it is the SINE
# function. In an audio/DSP repo it produced 3 of 7 hits, every one of them on impeccable English
# ("# ... since math.sin is a looping function"). Spanish prose containing `sin` almost always
# trips some other word in this list, so the loss of signal is small and the noise saved is not.
#
# `del` STAYS: measured over 74 hits it was genuine Spanish every time ("el nodo DEL frontmatter").  # lang-ok
# It is also a Python keyword, but that collision is handled where it belongs -- `_is_commentish`
# refuses to read a `del x` statement as prose -- rather than by blunting the dictionary.  # lang-ok
#
# The list below trips the detector on itself, so every line carries the escape hatch. That the
# gate has to exempt its own dictionary is a good smoke test that the escape hatch works at all.
_WORDS = (
    r"que|para|con|los|las|del|por|una|como|pero|desde|cuando|porque|sobre|hasta|"  # lang-ok
    r"solo|s[oó]lo|as[ií]|aqu[ií]|esto|esta|este|ese|esa|cada|hay|ser|est[aá]n?|son|"  # lang-ok
    r"tiene|hace|puede|debe|siempre|nunca|tambi[eé]n|adem[aá]s|entonces|aunque|mientras|"  # lang-ok
    r"antes|despu[eé]s|ahora|luego|donde|qui[eé]n|cu[aá]l|nada|algo|otro|otra|mismo|misma"  # lang-ok
)
_SPANISH = re.compile(rf"\b(?:{_WORDS})\b|[áéíóúñ¿¡]", re.IGNORECASE)
_ESCAPE = "lang-ok"
_EXTS = (".py",)
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "_build", "backup", "dist", "build"}
def _baseline_path() -> str:
    """Where the baseline lives. Resolved against the REPO, never against this file.

    WHY (2026-08-11). It used to be `dirname(__file__)/lang_gate_baseline.json` — i.e. next to the
    tool. That works only because the tool happens to sit inside the repo it checks: the moment it
    is installed anywhere else (a venv, `uvx`, a shared bin) the gate reads and writes a baseline in
    a directory that has nothing to do with the project, and silently reports a clean tree. It was
    correct by accident of location, which is not a property you want under a gate.

    Resolution order: `LANG_GATE_BASELINE` (explicit wins) -> `<git root>/tools/lang_gate_baseline.json`
    -> next to this file, only if there is no git repo at all. The default keeps the file exactly
    where every consumer already has it, so this fix moves nothing and breaks no one.
    """
    env = os.environ.get("LANG_GATE_BASELINE")
    if env:
        return os.path.abspath(env)
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return os.path.join(r.stdout.strip(), "tools", "lang_gate_baseline.json")
    except Exception:
        pass
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang_gate_baseline.json")


_BASELINE = _baseline_path()


def _is_commentish(line: str) -> bool:
    """True for lines that carry prose: comments and docstring bodies.

    Intentionally crude. Real string literals holding user-facing Spanish would be missed, and a
    line inside a multi-line docstring is only caught when it looks like prose. That is the right
    trade: this gate exists to stop new Spanish PROSE, and a stricter parser would cost false
    positives on data (URLs, test fixtures, sample content) that nobody wants to translate.

    `del` is in the keyword list for a reason that took measuring to see: `del frame` is a whole
    Python statement with no punctuation at all, so without it the line reads as prose and the
    dictionary (where `del` is high-signal Spanish) fires on real code.
    """
    s = line.strip()
    if s.startswith("#"):
        return True
    if '"""' in s or "'''" in s:
        return True
    # A prose-looking line with no code punctuation: likely inside a docstring.
    return bool(s) and not re.search(r"[=(){}\[\];:]|^\s*(def|class|import|from|return|del)\b", s)


def _offending(line: str) -> bool:
    if _ESCAPE in line:
        return False
    return _is_commentish(line) and bool(_SPANISH.search(line))


def scan_tree(root: str) -> list[tuple[str, int, str]]:
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(_EXTS):
                continue
            p = os.path.join(dirpath, fn)
            try:
                lines = open(p, encoding="utf-8").read().splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for i, ln in enumerate(lines, 1):
                if _offending(ln):
                    hits.append((os.path.relpath(p, root), i, ln.strip()))
    return hits


def scan_diff(ref: str | None) -> list[tuple[str, int, str]]:
    """Offending lines among those ADDED by the diff. Only `+` lines are judged: touching a file
    must not make you responsible for prose you did not write."""
    cmd = ["git", "diff", "--unified=0"] + ([ref] if ref else ["--cached"])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"lang-gate: cannot read the diff ({exc}) -> SKIPPING", file=sys.stderr)
        return []
    hits, path, lineno = [], None, 0
    for ln in out.splitlines():
        if ln.startswith("+++ b/"):
            path = ln[6:]
            continue
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", ln)
        if m:
            lineno = int(m.group(1))
            continue
        if ln.startswith("+") and not ln.startswith("+++"):
            body = ln[1:]
            if path and path.endswith(_EXTS) and _offending(body):
                hits.append((path, lineno, body.strip()))
            lineno += 1
    return hits


def _report(hits, header: str) -> None:
    print(header, file=sys.stderr)
    for path, lineno, text in hits[:25]:
        print(f"  {path}:{lineno}: {text[:110]}", file=sys.stderr)
    if len(hits) > 25:
        print(f"  ... and {len(hits) - 25} more", file=sys.stderr)
    # No document is named here on purpose: this file is vendored verbatim across repos that keep
    # their conventions in different places. The pointer lives in the hook/workflow that ran us.
    print("\nCode and comments are English in this repo.", file=sys.stderr)
    print(f"A genuine false positive is silenced with a trailing `# {_ESCAPE}`.", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="English-only ratchet gate.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--diff", nargs="?", const=None, metavar="REF",
                   help="judge only lines ADDED (default: the staged diff)")
    g.add_argument("--baseline", action="store_true",
                   help="whole tree; fail if the count grew vs the baseline")
    g.add_argument("--update-baseline", action="store_true",
                   help="record the current (lower) count after translating")
    args = ap.parse_args()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if args.diff is not None or "--diff" in sys.argv:
        hits = scan_diff(args.diff)
        if hits:
            _report(hits, f"lang-gate: {len(hits)} NEW line(s) that look like Spanish:")
            return 1
        print("lang-gate: OK -- no new Spanish in the added lines.")
        return 0

    hits = scan_tree(root)
    n = len(hits)
    # PER-FILE counts, not just a total. A bare total answers "it grew" and then lists 25 arbitrary
    # legacy lines, which is useless for fixing it: the offenders are buried among 1300 tolerated
    # ones. With a per-file map the gate can name the files that actually grew -- the only thing the
    # person reading a red build needs. Learned the hard way on 2026-08-09: the ratchet went red and
    # the report pointed at files that had been there for months.
    per_file = {}
    for path, _, _ in hits:
        per_file[path] = per_file.get(path, 0) + 1
    if args.update_baseline:
        with open(_BASELINE, "w", encoding="utf-8") as fh:
            json.dump({"count": n,
                       "note": "Legacy Spanish lines. This number may only DECREASE.",
                       "files": dict(sorted(per_file.items()))}, fh, indent=2)
            fh.write("\n")
        print(f"lang-gate: baseline updated to {n} across {len(per_file)} file(s).")
        return 0

    try:
        base = json.load(open(_BASELINE, encoding="utf-8"))["count"]
    except (OSError, ValueError, KeyError):
        print(f"lang-gate: no readable baseline; current count is {n}. "
              f"Create it with --update-baseline.", file=sys.stderr)
        return 1
    if n > base:
        # Name the files that GREW, not the first 25 hits in the tree.
        base_files = {}
        try:
            base_files = json.load(open(_BASELINE, encoding="utf-8")).get("files") or {}
        except (OSError, ValueError):
            pass
        if base_files:
            grew = {f: (per_file[f], base_files.get(f, 0))
                    for f in per_file if per_file[f] > base_files.get(f, 0)}
            print(f"lang-gate: the count GREW: {n} > baseline {base}.", file=sys.stderr)
            print("These files gained Spanish lines (translate them; do NOT raise the baseline "
                  "-- that would disarm the ratchet):", file=sys.stderr)
            for f, (now, was) in sorted(grew.items(), key=lambda kv: kv[1][0] - kv[1][1], reverse=True):
                print(f"  {f}: {was} -> {now}  (+{now - was})", file=sys.stderr)
                for path, lineno, text in hits:
                    if path == f:
                        print(f"      line {lineno}: {text[:100]}", file=sys.stderr)
            print(f"\nA genuine false positive is silenced with a trailing `# {_ESCAPE}`.",
                  file=sys.stderr)
        else:
            # Baseline written before per-file counts existed: fall back, and say why it is vague.
            _report(hits[:25], f"lang-gate: the count GREW: {n} > baseline {base}. "
                               f"(Baseline has no per-file map, so these are tree hits, not the new "
                               f"ones -- re-seed with --update-baseline from a GREEN commit.)")
        return 1
    if n < base:
        print(f"lang-gate: OK -- and it went DOWN ({n} < {base}). "
              f"Lock the win in with --update-baseline.")
        return 0
    print(f"lang-gate: OK -- {n} legacy line(s), unchanged vs the baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
