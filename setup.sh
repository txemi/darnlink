#!/usr/bin/env bash
# Activate this repo's git hooks — one-time, per clone.
#
# Wires up three events, all of them by flipping one switch (core.hooksPath=hooks):
#   git commit  ->  hooks/pre-commit   the darnlink quality gate (broken/unresolvable link,
#                                      invalid YAML frontmatter)
#               ->  hooks/commit-msg   the commit MESSAGE must be English (tools/lang_gate.py)
#   git push    ->  hooks/pre-push     the same gate over the whole repo
# The gates themselves live in those files; this script only flips the switch.
# git won't auto-run versioned hooks on clone (security) — hence this installer.
#
# Not needed if your machine already has a global hook dispatcher — but note that a dispatcher
# only runs the events it has an entry for, and a missing one is a SILENT no-op: the repo's hook
# is there, executable and never called. `commit-msg` is the newest of the three.
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
