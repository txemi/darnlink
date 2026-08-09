#!/usr/bin/env python3
"""Fail if any Markdown link points at a path that does not exist (the `dangling` axis).

Why this file exists at all
---------------------------
A dangling link is invisible to every other axis darnlink has. It is not `unresolvable` -- that is a
*robust* link whose uuid died. It is not `to robustify` -- there is nothing to anchor to, because the
target is not there. So it falls through all of them, and `check` reports it as **informational
only**: the gating *policy* lives in `recipes/darnlink-gate`, which reads `check --json` and decides.

The CLI deliberately has no `--dangling-fails` flag (the recipe owns policy, the library owns
findings), so darnlink's own quality gate cannot dogfood the axis by passing a flag. It makes the
same judgment the recipe makes, from the same JSON.

Fail-closed at zero, on purpose
-------------------------------
This mirrors the strictest rung the recipe offers (`"dangling": "repo"`), which is what four repos in
the consuming fleet already run. darnlink measures zero, so demanding zero costs nothing -- and a
ratchet that costs nothing is one you take immediately, before the debt arrives.

It would have caught the one that existed: `specs/011-directory-links/spec.md` illustrated the
feature with *"see the [deployment guide](ops/deploy/)"* -- written as a real link to a path that has
never existed in this repo. That is the shape to watch for: **an illustration must not be a link**,
because a reader who clicks it gets a 404 from our own documentation.

Usage:
    python3 tools/dangling_gate.py            # scan the repo root
    python3 tools/dangling_gate.py <path>     # scan somewhere else
"""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    # `uv run` so this uses the checked-out source, not an installed release: the gate must judge the
    # tree it is being run on, otherwise a bug in the current branch could hide behind an older wheel.
    proc = subprocess.run(
        ["uv", "run", "darnlink", "check", root, "--json"],
        capture_output=True,
        text=True,
    )
    # `check` exits non-zero when it finds integrity/strict problems; that is a different axis and the
    # earlier steps of check.sh already failed on it. What matters here is whether we got usable JSON.
    if not proc.stdout.strip():
        print("dangling gate: darnlink produced no JSON -- cannot judge, failing closed.", file=sys.stderr)
        print(proc.stderr.strip()[:2000], file=sys.stderr)
        return 2
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"dangling gate: unparseable JSON from darnlink ({exc}) -- failing closed.", file=sys.stderr)
        return 2

    findings = data.get("dangling", {}).get("findings", [])
    if not findings:
        print("dangling gate: 0 links pointing at a non-existent target -- ok.")
        return 0

    print(f"dangling gate: {len(findings)} link(s) whose target does not exist:", file=sys.stderr)
    for f in findings:
        print(f"  {f.get('file', '?')}:{f.get('line') or '?'}  {f.get('detail', '')}", file=sys.stderr)
    print(
        "Fix the path, or stop making it a link if it is an illustration.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
