# Feature Specification: glob patterns in `--exclude`

**Feature Branch**: `009-glob-excludes`

**Created**: 2026-07-17

**Status**: Draft

**Input**: `--exclude` matches a directory by **exact name** only. A repo that wants to skip a *family*
of directories (a naming convention, e.g. "ignore everything named `old`": `old`, `old_html`,
`001_old`, `.github.old`) must list every one by hand and keep the list in sync as new ones appear —
drift. Let `--exclude` take a **glob**.

## The change

`--exclude PATTERN` matches a directory name by **glob** (`fnmatch`, case-sensitive) instead of exact
name. **Backward-compatible:** a pattern with no wildcards matches exactly, so every existing invocation
(`--exclude node_modules`, `--exclude external_repos`) behaves identically. The glob is purely additive.

```
darnlink . --exclude 'old' --exclude 'old_*' --exclude '*_old' --exclude '*.old'   # the whole 'old' family, no drift
```

### Why word-boundary globs, not `*old*`

`--exclude '*old*'` would over-match — `folder` (f-**old**-er), `holder`, `bold`. So the *pattern
author* expresses the boundary with a small set of globs (`old`, `old_*`, `*_old`, `*.old`) rather than
darnlink guessing intent. darnlink just does plain `fnmatch`; the boundaries live in the patterns.

## Constitution Check

- **P-I (Links & UUIDs Only, NON-NEGOTIABLE):** this only refines *which directories are scanned* — the
  same knob `--exclude` already is. No new external state, no git, no document semantics. In-bounds. ✅
- **P-III (self-contained):** nothing new stored; a CLI arg, like `ruff`/`ripgrep` globs. ✅
- **P-IV (Deterministic):** `fnmatchcase` is case-sensitive and pure → output stays a function of the
  tree + the patterns (no locale/OS case-folding surprises). ✅
- No naming or scope tension — this is a straightforward capability bump to an existing flag.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** `--exclude PATTERN` MUST skip any directory whose **name** matches PATTERN by `fnmatch`
  (case-sensitive).
- **FR-002** A PATTERN with no wildcard characters MUST match exactly the same directories as before
  (backward compatibility — `--exclude node_modules` is unchanged).
- **FR-003** Matching is on the directory **basename** only (not the path), consistent with today's
  behaviour and with how `iter_markdown_files` prunes `os.walk`'s `dirnames`.
- **FR-004** `DEFAULT_EXCLUDES` (plain names) MUST keep matching exactly (they contain no wildcards).

### Key Entities

- No new entity. `iter_markdown_files`'s prune step changes from `d not in excludes` to
  `not any(fnmatchcase(d, pat) for pat in excludes)`.

## Acceptance

- `--exclude old` skips `old/` but **not** `folder/`, `bold/`, `old_html/` (exact, no wildcard).
- `--exclude 'old_*'` skips `old_html/`, `old_impl/` but not `old/` or `holder/`.
- `--exclude '*_old'` skips `001_old/` but not `folder/`.
- `--exclude '*.old'` skips `.github.old/`.
- `--exclude node_modules` behaves exactly as before (regression).
- The four `old` globs together skip the whole family and nothing spurious (`folder/`, `holder/` stay).

## Out of scope

- Path/glob-star matching across separators (`**/build`) — basename-only, as today.
- Regex excludes — globs cover the need; regex would be heavier and less familiar.
- File-level excludes (this is directory pruning); opting a single file out is the
  `<!-- darnlink-ignore-file -->` / `ignore-links` markers' job (spec 003/006).
