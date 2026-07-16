#!/usr/bin/env bash
# Local quality gate for darnlink — mirrors CI (.github/workflows/ci.yml) so you can run the
# same checks before pushing instead of waiting for CI.
#
#   tests + darnlink self-check (dogfood: darnlink gates its own Markdown links/frontmatter).
#
# Exits non-zero on the first failure.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

uv sync --extra dev   # set up the environment (project + dev deps), like CI's install step
uv run pytest -q
uv run darnlink .              # repair check: robust links must not be broken
uv run darnlink . --robustify  # strict check (fail-closed): every anchorable link must be robust
