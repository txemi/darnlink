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
# MAX self-gate (dogfood the strictest setting): every link's target must carry a uuid.
# README.md is deny-listed — it's the PyPI/GitHub landing page, so it stays frontmatter-free
# (its OUTBOUND links are still anchored with invisible <!-- uuid --> comments; only a frontmatter
# uuid would show on the package page, which we don't want). See docs/elevating-your-link-gate.md.
uv run darnlink . --robustify --create-frontmatter --no-create-frontmatter-for README.md
