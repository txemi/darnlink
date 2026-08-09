#!/usr/bin/env bash
# Local quality gate for darnlink — mirrors CI (.github/workflows/ci.yml) so you can run the
# same checks before pushing instead of waiting for CI.
#
#   tests + darnlink self-check (dogfood: darnlink gates its own Markdown links/frontmatter).
#
# Exits non-zero on the first failure.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# English-only gate. The rule is not new — CLAUDE.md has said "Everything in this repo is written
# in English" since the start — but until now nothing checked it. Runs FIRST because it is pure
# stdlib: it costs a second and needs no environment, so it fails before `uv sync` makes you wait.
# Fail-closed (baseline pinned at 0): darnlink measures zero offending lines, so demanding zero
# costs nothing. Sibling repos that adopted the rule late run the same tool against a non-zero
# baseline that may only shrink.
python3 tools/lang_gate.py --baseline

uv sync --extra dev   # set up the environment (project + dev deps), like CI's install step
uv run pytest -q
uv run darnlink .              # repair check: robust links must not be broken
# MAX self-gate (dogfood the strictest setting): a link to a file with no uuid fails the gate.
# README.md is deny-listed — it's the PyPI/GitHub landing page, so it stays frontmatter-free (its
# OUTBOUND links are still anchored with invisible <!-- uuid --> comments; only a frontmatter uuid would
# show on the package page, which we don't want). See docs/elevating-your-link-gate.md.
uv run darnlink . --robustify --create-frontmatter --no-create-frontmatter-for README.md

# Dangling axis (dogfood `dangling: repo`, the strictest rung the recipe offers). Runs LAST
# because it shells out to darnlink again; see tools/dangling_gate.py for why it lives in its own
# file and why it is fail-closed at zero.
python3 tools/dangling_gate.py

