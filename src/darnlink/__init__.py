"""darnlink — auto-healing Markdown links.

Anchor Markdown links to a UUID so they survive file moves:
- repair: rewrite a robust link's path to wherever its UUID now lives.
- robustify: upgrade a plain link to a robust one.

Plain Markdown, no database, no editor lock-in. Dry-run by default.
See the project Constitution in .specify/memory/constitution.md.
"""

# DERIVED from the installed package metadata, never written by hand. Hand-written, it said "0.5.0"
# while pyproject.toml said 0.22.0 — seventeen minors adrift, and nothing failed, because nothing
# reads it yet. That is exactly the shape of a mine: harmless until the day someone adds `--version`
# or trusts `darnlink.__version__`, at which point the tool lies about itself with a straight face.
#
# LAZY (PEP 562), and that is not premature optimisation: `importlib.metadata` drags in the whole
# `email` stack, and importing it at module level cost **+34 %** on `import darnlink.cli` (median of
# interleaved runs, same tree, only this file swapped). Quoted as a percentage on purpose: two
# independent runs of the same A/B agreed on ~34 % and disagreed on the absolute (+33 ms vs +45 ms),
# so the milliseconds are the machine's, not the change's. darnlink runs as a pre-commit hook on
# every commit across a fleet, so a third of the startup for an attribute nothing reads yet is the
# wrong trade. This way the cost lands only on whoever actually asks for the version.
__all__ = ["__version__"]


def __getattr__(name: str) -> str:
    if name != "__version__":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib.metadata import PackageNotFoundError, version

    try:
        # NOTE: this is the version of the INSTALLED distribution, which is not necessarily the
        # source tree you are importing — running from a checkout against an older installed wheel
        # reports the wheel's. Right for "what am I running as a tool", wrong for "what is this code".
        return version("darnlink")
    except PackageNotFoundError:  # a source tree that was never installed — say so, don't guess
        return "0+unknown"


def __dir__() -> list:
    # PEP 562 asks for this alongside `__getattr__`: without it the attribute exists and answers
    # `hasattr`, but `dir(darnlink)` does not list it — so tab-completion and introspection say the
    # version is not there while `darnlink.__version__` happily returns it.
    return sorted(set(globals()) | {"__version__"})
