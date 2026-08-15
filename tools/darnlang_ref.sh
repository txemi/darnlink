#!/usr/bin/env bash
# SINGLE SOURCE OF THE darnlang VERSION for this repo.
#
# Sourced by tools/check.sh, the hooks and every CI job. To move version you change the ref HERE and
# nowhere else: a version pinned in five places drifts, and the drift stays invisible until two
# surfaces disagree about whether the tree is clean.
#
# Pinned, never floating: `uvx darnlang` alone resolves to whatever is newest, so an upstream
# detector change could turn this repo red on a day nobody touched it. Upgrades are a decision.
#
# WHY A PACKAGE AND NOT `tools/lang_gate.py` ANY MORE (2026-08-13). That file was vendored byte for
# byte into four repos, and the copies had already diverged in three different directions. Two
# adversarial reviews of the extracted package then found FOUR false greens that all four copies
# shared and none of them had a test for. This repo is where the prose surfaces were invented and
# where they were most complete, so migrating it is not a downgrade in any axis -- verified before
# switching, surface by surface.
export DARNLANG_REF="git+https://github.com/txemi/darnlang@v0.9.1"
