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

Modes:

    lang_gate.py --diff [REF]     # pre-commit / PR: only ADDED lines (default REF: staged)
    lang_gate.py --baseline       # CI: whole tree; fails if the count GREW vs the baseline file
    lang_gate.py --update-baseline  # after translating: write the new (lower) count
    lang_gate.py --prose FILE|-   # free prose: a commit message, an issue/PR title+body

WHY A PROSE MODE, AND WHY IT IS THE ONE THAT WAS MISSING (2026-08-11). The three modes above judge
only what git tracks, and only lines that look like comments. But the rule has always covered
commit messages, PR titles/descriptions and issues too -- and those are written straight into
GitHub, where no file gate can ever see them. Measured on this repo the day the hole was found:
the tree was clean while 2 of 2 open issues, 4 PR titles and 7 commit subjects on `main` were in
Spanish, permanently, on a public repository. A gate that guards only the surface nobody publishes
on is not a gate, it is a decoration. `--prose` reads that text from a file (or stdin) so a
`commit-msg` hook and a CI workflow can feed it what GitHub is about to show the world.

The detector is deliberately a heuristic: Spanish function words plus accented characters, looked
for only in comments, docstrings and prose. It cannot be exact -- `no`, `final` and `total` are
valid in both languages -- so a genuine false positive is silenced with a trailing `# lang-ok`
(`<!-- lang-ok -->` in Markdown, where a `#` is a heading and not a comment).

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
# `solo` was dropped on 2026-08-11 for the same reason as `sin`, and again only after measuring: it  # lang-ok
# is an ordinary English word ("fine solo; with several sessions it is not"), and that sentence --
# impeccable English in a PR description -- was 1 of the 8 hits in the first sweep of this repo's
# pull requests. Nothing is lost that matters: the ACCENTED form is still caught by the accent
# class, and unaccented Spanish prose containing it reliably trips some other word in the list.
#
# The list below trips the detector on itself, so every line carries the escape hatch. That the
# gate has to exempt its own dictionary is a good smoke test that the escape hatch works at all.
_WORDS = (
    r"que|para|con|los|las|del|por|una|como|pero|desde|cuando|porque|sobre|hasta|"  # lang-ok
    r"as[ií]|aqu[ií]|esto|esta|este|ese|esa|cada|hay|ser|est[aá]n?|son|"  # lang-ok
    r"tiene|hace|puede|debe|siempre|nunca|tambi[eé]n|adem[aá]s|entonces|aunque|mientras|"  # lang-ok
    r"antes|despu[eé]s|ahora|luego|donde|qui[eé]n|cu[aá]l|nada|algo|otro|otra|mismo|misma"  # lang-ok
)
_SPANISH = re.compile(rf"\b(?:{_WORDS})\b|[áéíóúñ¿¡]", re.IGNORECASE)
_ESCAPE = "lang-ok"

# Two families, judged by different rules -- see `_is_prose`.
#   CODE: only comment/docstring lines are prose; the rest is code and must not be read as language.
#   DOC : the whole file is prose, minus fenced code blocks and inline `code` spans.
# Docs were outside the gate until 2026-08-11 even though the rule always covered them ("code,
# comments, docstrings, documentation"). The cost of closing it was measured before doing it: five
# lines, all in one CHANGELOG entry. A rule that is stated and not measured is a rule nobody knows
# is being broken.
_CODE_EXTS = (".py",)
_DOC_EXTS = (".md",)
_EXTS = _CODE_EXTS + _DOC_EXTS
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "_build", "backup", "dist", "build"}
_FENCE = re.compile(r"^\s*(?:```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`")
_URL = re.compile(r"https?://\S+")


_BASELINE_NAME = "lang_gate_baseline.json"


def _project_root() -> str:
    """The one tree this run is about: the git repo, or the tool's parent if there is no repo.

    WHY THIS IS ONE FUNCTION (2026-08-12). This tool needs two paths -- the tree to scan and the
    baseline to compare it against -- and they must describe the SAME project or the ratchet means
    nothing. Both used to come from `__file__`. Both were wrong in the same way, which is exactly
    why nobody noticed: they agreed, so the gate worked -- correct by accident of location.

    Fixing only the baseline (2026-08-11) was strictly worse than leaving both wrong. Run from a
    project carrying 1242 legacy lines with the tool installed elsewhere, it read the real baseline
    and compared it against a count taken from an unrelated tree: `0 < 1242`, so it printed
    "OK -- and it went DOWN", exited 0 over untouched debt, and invited the user to run
    `--update-baseline`, which would have written that 0 into a tracked file. The verdict was not
    even deterministic -- the scanned tree was whatever sat next to the tool, so the same command
    returned green or red depending on what happened to be in the neighbouring directory.

    So there is ONE resolution and everything derives from it. Two paths that must agree should not
    be two decisions.
    """
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return os.path.realpath(r.stdout.strip())
        why = (r.stderr.strip().splitlines()[0] if r.stderr.strip()
               else "not inside a git repo")
    except Exception as exc:  # git missing, timeout, anything
        why = f"cannot ask git for the repo root ({exc.__class__.__name__})"
    # FALL BACK TO THE CWD, NOT TO THE TOOL. Where the tool sits says nothing about what the user
    # asked to check; the directory they ran it from does. Falling back to `dirname(__file__)` is
    # how a shared-bin install ends up judging the tool's own repo -- or `$HOME` -- and reporting
    # OK about a project it never looked at. And say it out loud: this file announces every other
    # degradation it makes, and a gate that silently picks a different tree is the bug above.
    print(f"lang-gate: {why} -> falling back to the current directory", file=sys.stderr)
    return os.path.realpath(os.getcwd())


def _is_within(path: str, root: str) -> bool:
    """True if `path` lives inside `root`. Used to refuse cross-project baselines."""
    try:
        root = os.path.realpath(root)
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError:  # different drives on Windows
        return False


def _baseline_path(root: str) -> str:
    """Where the baseline lives: `<root>/tools/`, derived from `root` and from nothing else.

    NO FALLBACK TO THE TOOL'S OWN DIRECTORY, and the reason is worth writing down because a first
    attempt at this fix had one. It looked harmless -- "if there is no baseline at the default but
    one sits beside the tool, and the tool is inside `root`, it must be the same project" -- and it
    reopened the exact hole this function exists to close. A vendored copy or a submodule (tool AND
    its baseline) lives inside `root` and satisfies that test while belonging to a different
    project. Measured: a host repo with no baseline of its own, carrying `third_party/x/tools/`
    whose baseline said 1242, reported "OK -- and it went DOWN (0 < 1242)" with rc=0 and then let
    `--update-baseline` overwrite that tracked 1242 with 0.

    "Inside the tree" is not the same question as "belongs to this project", and no cheap predicate
    tells them apart. So there is one location, and a consumer with an unusual layout uses
    `LANG_GATE_BASELINE` -- an explicit choice, not a guess made on their behalf.
    """
    env = os.environ.get("LANG_GATE_BASELINE")
    if env:
        # Relative means "relative to the project", not to wherever you happened to `cd`. Against
        # the cwd, the same command gives a different verdict from the root and from a subdirectory
        # -- exactly the dependency this whole change exists to remove.
        path = env if os.path.isabs(env) else os.path.join(root, env)
        path = os.path.abspath(path)
        # Reads are not guarded (the whole point of the escape hatch is pointing somewhere odd),
        # but comparing a count from `root` against a baseline from elsewhere is exactly the #49
        # failure, so it does not get to happen quietly.
        if not _is_within(path, root):
            print(f"lang-gate: LANG_GATE_BASELINE points outside the tree being scanned. The "
                  f"comparison spans two projects.\n  scanned : {root}\n  baseline: {path}",
                  file=sys.stderr)
        return path
    default = os.path.join(root, "tools", _BASELINE_NAME)
    # Check the DEFAULT too. It looks impossible to leave the tree from `<root>/tools/`, but a
    # symlinked `tools/` (or a symlinked baseline file) does exactly that, with no env var and no
    # user action at run time -- the only remaining silent path across projects.
    if os.path.exists(default) and not _is_within(default, root):
        print(f"lang-gate: {default} resolves outside the tree being scanned (symlink?). The "
              f"comparison spans two projects.\n  scanned : {root}", file=sys.stderr)
    return default


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


def _strip_verbatim(line: str) -> str:
    """Drop the parts of a prose line that are not language: inline `code` spans and URLs.

    Without this, documentation is unjudgeable: a path like `docs/investigacion.md` or a URL with a
    Spanish slug is not prose in another language, it is an identifier that happens to spell one --
    and a gate that fires on identifiers is a gate that gets bypassed.
    """
    return _URL.sub("", _INLINE_CODE.sub("", line))


def _is_prose(path: str, line: str, in_fence: bool) -> bool:
    """Whether this line should be read as language at all, by file family.

    Docs invert the default: in a `.md` everything is prose EXCEPT fenced blocks, whereas in a
    `.py` everything is code EXCEPT comments and docstrings. Judging a `.md` with the code rule
    silently misses most of it -- `_is_commentish` rejects any line carrying `:` or `(`, which is
    most of a written paragraph. That is how the five Spanish lines in this repo's own CHANGELOG
    sat under a green gate.
    """
    if path.endswith(_DOC_EXTS):
        return not in_fence and bool(_strip_verbatim(line).strip())
    return _is_commentish(line)


def _offending(line: str, path: str = "x.py", in_fence: bool = False) -> bool:
    if _ESCAPE in line:
        return False
    if not _is_prose(path, line, in_fence):
        return False
    return bool(_SPANISH.search(_strip_verbatim(line) if path.endswith(_DOC_EXTS) else line))


def _scan_lines(path: str, lines: list[str]) -> list[tuple[int, str]]:
    """Offending lines of one file's content, tracking fenced code blocks for docs."""
    hits, in_fence = [], False
    for i, ln in enumerate(lines, 1):
        if path.endswith(_DOC_EXTS) and _FENCE.match(ln):
            in_fence = not in_fence
            continue
        if _offending(ln, path, in_fence):
            hits.append((i, ln.strip()))
    return hits


def scan_tree(root: str) -> list[tuple[str, int, str]]:
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(_EXTS):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            try:
                lines = open(p, encoding="utf-8").read().splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            hits.extend((rel, i, text) for i, text in _scan_lines(rel, lines))
    return hits


def _fenced_lines(path: str) -> set[int]:
    """Line numbers of `path` that sit inside a fenced code block, read from the working tree.

    A unified diff carries no fence state -- an added line inside a ``` block looks exactly like an
    added paragraph -- so a doc file has to be re-read to know. The post-image on disk is the right
    approximation for the two callers that matter (pre-commit and a PR range), and when the file is
    not readable the caller simply falls back to judging the line as prose, which errs toward MORE
    findings rather than fewer. That is the correct direction for a gate.
    """
    inside, fenced, n = False, set(), 0
    try:
        for n, ln in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
            if _FENCE.match(ln):
                inside = not inside
                fenced.add(n)
            elif inside:
                fenced.add(n)
    except (OSError, UnicodeDecodeError):
        return set()
    return fenced


def scan_diff(ref: str | None) -> list[tuple[str, int, str]]:
    """Offending lines among those ADDED by the diff. Only `+` lines are judged: touching a file
    must not make you responsible for prose you did not write."""
    cmd = ["git", "diff", "--unified=0"] + ([ref] if ref else ["--cached"])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"lang-gate: cannot read the diff ({exc}) -> SKIPPING", file=sys.stderr)
        return []
    hits, path, lineno, fenced = [], None, 0, set()
    for ln in out.splitlines():
        if ln.startswith("+++ b/"):
            path = ln[6:]
            fenced = _fenced_lines(path) if path.endswith(_DOC_EXTS) else set()
            continue
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", ln)
        if m:
            lineno = int(m.group(1))
            continue
        if ln.startswith("+") and not ln.startswith("+++"):
            body = ln[1:]
            if path and path.endswith(_EXTS) and _offending(body, path, lineno in fenced):
                hits.append((path, lineno, body.strip()))
            lineno += 1
    return hits


def scan_prose(text: str, *, git_comments: bool = False) -> list[tuple[int, str]]:
    """Offending lines of free prose: a commit message, or an issue/PR title+body.

    Judged with the DOC rule -- everything is language except fenced blocks, inline `code` and
    URLs -- because that is what these texts are. Two deliberate details:

    * `git_comments` drops lines starting with `#`. In a commit message those are git's own
      template, which is written in the user's LOCALE and would fire the detector on text the
      author never wrote and git is about to strip anyway. In Markdown a `#` is a heading, i.e.
      prose that must be judged, so the two cases cannot share a default.
    * A scissors line (`# ------------------------ >8 ------------------------`) ends the message:
      everything below it is the diff `git commit --verbose` pastes in, and judging somebody's
      code as prose is how a gate earns a reputation for lying.
    """
    hits, in_fence = [], False
    for i, ln in enumerate(text.splitlines(), 1):
        if git_comments and ln.startswith("# ------------------------ >8"):
            break
        if git_comments and ln.startswith("#"):
            continue
        if _FENCE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence or _ESCAPE in ln:
            continue
        if _SPANISH.search(_strip_verbatim(ln)):
            hits.append((i, ln.strip()))
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
    g.add_argument("--prose", metavar="FILE",
                   help="judge free prose (commit message, issue/PR title+body); '-' reads stdin")
    ap.add_argument("--git-comments", action="store_true",
                    help="with --prose: drop '#' lines and everything after the scissors (commit message)")
    ap.add_argument("--label", default="text",
                    help="with --prose: what to call the text in the error message")
    args = ap.parse_args()
    root = _project_root()
    baseline_path = _baseline_path(root)

    if args.prose:
        try:
            text = sys.stdin.read() if args.prose == "-" else open(args.prose, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError) as exc:
            # Fail CLOSED. An unreadable message is not an English message, and the whole point of
            # this mode is the surfaces where nothing else is watching.
            print(f"lang-gate: cannot read {args.prose} ({exc})", file=sys.stderr)
            return 1
        hits = scan_prose(text, git_comments=args.git_comments)
        if hits:
            print(f"lang-gate: this {args.label} does not look like English:", file=sys.stderr)
            for lineno, line in hits[:25]:
                print(f"  line {lineno}: {line[:110]}", file=sys.stderr)
            if len(hits) > 25:
                print(f"  ... and {len(hits) - 25} more", file=sys.stderr)
            print("\nCommit messages, PR titles/descriptions and issues are public, permanent and "
                  "part of this repo's documentation -- they are English like everything else.",
                  file=sys.stderr)
            print(f"A genuine false positive is silenced with `{_ESCAPE}` on that line.",
                  file=sys.stderr)
            return 1
        print(f"lang-gate: OK -- the {args.label} is English.")
        return 0

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
        # Never record a count measured on one tree into another tree's baseline. Unreachable with
        # the single-root resolution unless LANG_GATE_BASELINE says otherwise -- which is exactly
        # the case worth guarding, because `n` is a fact about `root` and nowhere else.
        if not _is_within(baseline_path, root):
            print(f"lang-gate: REFUSING to write. The baseline is outside the tree that was "
                  f"scanned, so the count would describe a different project.\n"
                  f"  scanned : {root}\n  baseline: {baseline_path}", file=sys.stderr)
            return 1
        try:
            os.makedirs(os.path.dirname(baseline_path) or ".", exist_ok=True)
            fh = open(baseline_path, "w", encoding="utf-8")
        except OSError as exc:
            print(f"lang-gate: cannot write the baseline at {baseline_path}: {exc}",
                  file=sys.stderr)
            return 1
        with fh:
            json.dump({"count": n,
                       "note": "Legacy Spanish lines. This number may only DECREASE.",
                       # What the number counts. Without it, widening coverage in this file is
                       # indistinguishable from a repo getting worse -- see below.
                       "scanned_exts": sorted(_EXTS),
                       "files": dict(sorted(per_file.items()))}, fh, indent=2)
            fh.write("\n")
        print(f"lang-gate: baseline updated to {n} across {len(per_file)} file(s) "
              f"(covering {', '.join(sorted(_EXTS))}).")
        return 0

    try:
        baseline = json.load(open(baseline_path, encoding="utf-8"))
        base = baseline["count"]
    except (OSError, ValueError, KeyError):
        print(f"lang-gate: no readable baseline; current count is {n}. "
              f"Create it with --update-baseline.", file=sys.stderr)
        return 1

    # COVERAGE CHANGED is not the same failure as THE REPO GOT WORSE, and conflating them is a lie
    # the ratchet tells on its own behalf. This file is vendored verbatim into every repo that runs
    # the gate, so the day it starts judging a new file family (`.md`, on 2026-08-11) every consumer
    # sees its count jump — through no fault of anyone's commit. Reported as "the count GREW", with
    # "do NOT raise the baseline" underneath, that message is actively wrong: raising it once IS the
    # correct move, exactly as when a repo adopts the rule late. So it gets its own message, and it
    # still fails, because a coverage change that nobody notices is how a gate silently loosens.
    covered = baseline.get("scanned_exts")
    if covered is not None and sorted(covered) != sorted(_EXTS):
        gained = sorted(set(_EXTS) - set(covered))
        lost = sorted(set(covered) - set(_EXTS))
        print(f"lang-gate: COVERAGE CHANGED -- the baseline counts {', '.join(sorted(covered))} "
              f"but this version judges {', '.join(sorted(_EXTS))}.", file=sys.stderr)
        if gained:
            print(f"  now also judged: {', '.join(gained)}  (current total: {n} line(s))",
                  file=sys.stderr)
        if lost:
            print(f"  NO LONGER judged: {', '.join(lost)} -- coverage went DOWN, which the ratchet "
                  f"exists to prevent. Do not accept this without knowing why.", file=sys.stderr)
        print("\nThis is an ADOPTION, not a regression: re-seed once with --update-baseline and "
              "then the number may only fall, as usual. (Adding a family is the same move as "
              "adopting the rule late, which is what the baseline was built for.)", file=sys.stderr)
        return 1

    if n > base:
        # Name the files that GREW, not the first 25 hits in the tree.
        base_files = {}
        try:
            base_files = baseline.get("files") or {}
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
        if not _is_within(baseline_path, root):
            print(f"lang-gate: the count ({n}) is BELOW the baseline ({base}), but they describe "
                  f"different projects -- see the warning above. Not treating this as a win.",
                  file=sys.stderr)
            return 1
        print(f"lang-gate: OK -- and it went DOWN ({n} < {base}). "
              f"Lock the win in with --update-baseline.")
        return 0
    print(f"lang-gate: OK -- {n} legacy line(s), unchanged vs the baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
