#!/usr/bin/env bash
# Activate this repo's git hooks — one-time, per clone.
#
# Wires up:  git commit  ->  hooks/pre-commit  ->  this repo's darnlink quality gate
#            (fails the commit if a Markdown link is broken/unresolvable, or a frontmatter
#            isn't valid YAML). This script only flips the switch (core.hooksPath=hooks);
#            the gate itself lives in hooks/pre-commit.
# git won't auto-run versioned hooks on clone (security) — hence this installer.
# Not needed if your machine already has the global hook dispatcher (toolbelt deploy.sh).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
current="$(git config --local --get core.hooksPath 2>/dev/null || true)"
if [[ -n "$current" && "$current" != "hooks" ]]; then
  echo "core.hooksPath already set to '$current' — leaving it (set it to 'hooks' yourself to use this repo's hook)."
  exit 0
fi
git config core.hooksPath hooks
echo "✓ hooks active — 'git commit' now runs the darnlink quality gate (hooks/pre-commit)."
echo "  bypass once with: git commit --no-verify"
