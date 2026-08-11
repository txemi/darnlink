"""Tests for `tools/lang_gate.py` — the English-only gate.

The gate had no tests at all until it started guarding PUBLIC, PERMANENT surfaces (commit messages,
PR titles, issues). That raised the cost of a silent regression from "a Spanish comment lands in a
file, and the next tree scan catches it" to "a Spanish issue title is published on a public repo and
nothing ever notices" — which is exactly what happened on 2026-08-11.

The gate is a heuristic, so what is worth pinning is not its dictionary but the three decisions that
make it usable: what counts as prose in each file family, what is exempt (fenced code, inline
`code`, URLs, the escape hatch), and the fact that it exits non-zero.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "lang_gate.py"

_spec = importlib.util.spec_from_file_location("lang_gate", TOOL)
lang_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lang_gate)


def _run(*args, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], input=stdin,
                          capture_output=True, text=True)


# --- prose mode: the surfaces that reach GitHub ------------------------------------------------

def test_spanish_commit_message_is_rejected():
    r = _run("--prose", "-", stdin="release: v0.20.4 — el peldano que faltaba entre repo y added-lines\n")
    assert r.returncode == 1
    assert "does not look like English" in r.stderr


def test_english_commit_message_passes():
    r = _run("--prose", "-", stdin="gate: a budget that makes the strictest rung adoptable\n")
    assert r.returncode == 0


def test_git_template_comments_are_not_judged():
    """git writes its template in the machine's LOCALE. Judging it fails the author for text they
    did not write and git is about to strip — the fastest way to get a hook uninstalled."""
    msg = "fix: keep the fence state per file\n\n# Por favor ingresa el mensaje de confirmacion\n"
    assert _run("--prose", "-", "--git-comments", stdin=msg).returncode == 0
    # …and without the flag the same text IS judged, so the exemption is the flag's doing.
    assert _run("--prose", "-", stdin=msg).returncode == 1


def test_verbose_commit_diff_below_the_scissors_is_not_judged():
    msg = ("fix: something\n"
           "# ------------------------ >8 ------------------------\n"
           "+# esto es una linea del diff que git pega con --verbose\n")
    assert _run("--prose", "-", "--git-comments", stdin=msg).returncode == 0


def test_fenced_block_in_an_issue_body_is_not_judged():
    """An issue body pastes real output. A Spanish path inside a fence is data, not prose."""
    body = ("The gate misses this case:\n\n"
            "```\n"
            "docs/investigacion.md: enlace roto para el destino que no existe\n"
            "```\n\n"
            "Expected: a finding.\n")
    assert _run("--prose", "-", stdin=body).returncode == 0


def test_inline_code_and_urls_are_not_judged():
    body = ("See `docs/investigacion-para-el-caso.md` and "
            "https://example.invalid/una-pagina-con-nombre-largo for the details.\n")
    assert _run("--prose", "-", stdin=body).returncode == 0


def test_escape_hatch_silences_a_line():
    assert _run("--prose", "-", stdin="quoting the original report: no funciona  lang-ok\n").returncode == 0


def test_unreadable_prose_file_fails_closed():
    """The whole point of this mode is the surfaces nothing else watches: an unreadable message is
    not an English message."""
    assert _run("--prose", str(REPO / "does-not-exist.txt")).returncode == 1


# --- file families -----------------------------------------------------------------------------

def test_markdown_prose_is_judged_although_it_carries_code_punctuation():
    """The regression that let five Spanish lines sit in this repo's own CHANGELOG under a green
    gate: `_is_commentish` rejects any line with a `:` or `(`, which is most written prose."""
    line = "en `darnlink-gate.json`). La receta falla abierta por defecto: un commit offline"
    assert lang_gate._offending(line, "CHANGELOG.md", False)
    assert not lang_gate._offending(line, "CHANGELOG.md", True)      # inside a fence
    assert not lang_gate._offending(line, "tools/x.py", False)       # code rule: not a comment


def test_python_code_is_still_judged_by_the_comment_rule():
    assert lang_gate._offending("# esto no puede pasar aqui", "tools/x.py")
    assert not lang_gate._offending("total = para_value + 1", "tools/x.py")


def test_tree_scan_covers_both_families():
    assert ".py" in lang_gate._EXTS and ".md" in lang_gate._EXTS


# --- widening coverage is an adoption, not a regression -----------------------------------------

def test_a_baseline_from_an_older_coverage_says_so_instead_of_blaming_the_repo():
    """This tool is vendored verbatim into other repos. The day it starts judging a new file family
    every consumer's count jumps through nobody's fault, and reporting that as "the count GREW —
    do NOT raise the baseline" would be advice that is exactly backwards."""
    baseline = REPO / "tools" / "lang_gate_baseline.json"
    original = baseline.read_text(encoding="utf-8")
    try:
        baseline.write_text('{"count": 0, "scanned_exts": [".py"], "files": {}}\n', encoding="utf-8")
        r = _run("--baseline")
        assert r.returncode == 1
        assert "COVERAGE CHANGED" in r.stderr
        assert "ADOPTION, not a regression" in r.stderr
        assert ".md" in r.stderr
    finally:
        baseline.write_text(original, encoding="utf-8")


def test_a_baseline_predating_the_field_is_not_treated_as_a_coverage_change():
    """Consumers on the old format have no `scanned_exts`. Absent must mean "unknown", not "empty",
    or every one of them fails on a field they have never heard of."""
    baseline = REPO / "tools" / "lang_gate_baseline.json"
    original = baseline.read_text(encoding="utf-8")
    try:
        baseline.write_text('{"count": 0, "files": {}}\n', encoding="utf-8")
        r = _run("--baseline")
        assert r.returncode == 0, r.stderr
        assert "COVERAGE CHANGED" not in r.stderr
    finally:
        baseline.write_text(original, encoding="utf-8")


# --- the repo's own state ----------------------------------------------------------------------

def test_this_repo_is_clean():
    """Dogfood: darnlink pins its baseline at 0, so the gate is fail-closed here."""
    r = _run("--baseline")
    assert r.returncode == 0, r.stderr
