# Tasks: darnlink core — robustify & repair

Test-first task breakdown for the Plan. Status as of the MVP.

## Phase 1 — Repair MVP (US1 + US3) — DONE

- [x] T001 Package skeleton: `pyproject.toml` (hatchling, entry point `darnlink`), `src/darnlink/`.
- [x] T002 [test] `tests/test_links.py` — robust-link grammar (detect, tolerant ws, plain-vs-robust, emit).
- [x] T003 `links.py` — `find_robust_links`, `find_plain_links`, `emit_robust_link` (grammar ported from reference).
- [x] T004 [test] `tests/test_paths.py` — `relative_link`, `resolve_href`, `split_fragment`, `is_local_md`.
- [x] T005 `paths.py` — path relative to the linking file; fragment handling.
- [x] T006 `frontmatter_index.py` — `build_index` → `uuid → file` (+ duplicate detection). *(Replaces the entity model.)*
- [x] T007 `report.py` — `Finding` / `Kind`.
- [x] T008 `repair.py` — `plan_repairs` (broken = href doesn't resolve to uuid's target) + `apply_repairs`.
- [x] T009 `cli.py` — `darnlink [path] [--write]`: dry-run report by default; exit codes for CI.
- [x] T010 [test] `tests/test_acceptance.py` — SC-001 move→repair-all, SC-002 idempotent, SC-003 dry-run zero-write, unresolvable/ambiguous reported not touched.
- [x] T011 `README.md`.

**Status: 13/13 tests pass; CLI verified (dry-run / --write / idempotent re-run).**

## Phase 2 — Robustify (US2) — DONE

- [x] T020 [test] robustify: plain→robust; reuse existing uuid; add uuid when missing; skip/create-frontmatter; idempotent; ignore URLs/non-md.
- [x] T021 `robustify.py` — two-phase (decide target uuids → annotate links + add target uuid), handles a file that is both target and linker.
- [x] T022 `frontmatter_edit.py` — surgical `uuid:` insertion (no YAML re-dump, no truncation); `--create-frontmatter` opt-in when target has none.
- [x] T023 CLI: `--robustify` + `--create-frontmatter` flags, wired into report and `--write`.

**Status: 19/19 tests pass; robustify CLI verified (dry-run / --write / --create-frontmatter).**

## Phase 3 — Hardening & distribution — IN PROGRESS

- [x] T030 `--json` output for CI.
- [~] T031 `--exclude NAME` (repeatable) to skip dirs (e.g. `--exclude external_repos`); full `.gitignore`
      respect still pending (note: a tracked submodule is not gitignored, so `--exclude` is the right lever for it).
- [x] T032 pre-commit hook config (`.pre-commit-hooks.yaml`) + GitHub Action (`.github/workflows/ci.yml`) + `quickstart.md`.
- [x] T033 smoke-test against a disposable `/tmp` clone of a real monorepo — **passed**: found & repaired
      3 real broken robust links whose targets had been moved/renamed, minimal diff, idempotent. (step06)
- [x] T034 publish the robust-link format as a standalone mini-spec (`FORMAT.md`).
