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
#
# WHERE IT IS FETCHED FROM can be changed; WHAT is fetched cannot. A host that must not reach GitHub
# (a fleet whose own forge carries the same repository and tags) sets DARNLANG_REPO_URL to that
# repository's URL. Only the address moves: the version below stays the single pin, and a URL that
# tries to carry its own `@ref` is refused, so no environment can pick another darnlang version.
# Refusing every `@` also refuses user info (`user:token@host`), so no credential travels in this
# variable; and since an ssh URL nearly always names a user, ssh:// is not offered at all.
DARNLANG_VERSION="v0.9.1"
DARNLANG_REPO_URL="${DARNLANG_REPO_URL:-https://github.com/txemi/darnlang}"
case "$DARNLANG_REPO_URL" in
  *@*) echo "darnlang_ref.sh: DARNLANG_REPO_URL must not contain '@' (the version is pinned here, not in the URL): $DARNLANG_REPO_URL" >&2
       return 2 2>/dev/null || exit 2 ;;
  http://*|https://*|file://*) ;;
  *) echo "darnlang_ref.sh: DARNLANG_REPO_URL must be an http(s):// or file:// URL: $DARNLANG_REPO_URL" >&2
     return 2 2>/dev/null || exit 2 ;;
esac
export DARNLANG_REF="git+${DARNLANG_REPO_URL}@${DARNLANG_VERSION}"
