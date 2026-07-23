# Changelog

All notable changes to darnlink are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.10.0] — 2026-07-23

### Changed
- **`--create-readme` skips folders holding downloaded/external content** (feature 014). A directory
  that directly contains a `.md` carrying `<!-- darnlink-ignore-file -->` (a downloaded mirror capture —
  a transcript, an extract) is the mirror's, not ours, so `--create-readme` no longer writes a README
  there. This is the surgical, provenance-based alternative to `--exclude`-ing a whole mirror tree:
  authored files inside the mirror stay robustifiable, and only the actual captures are skipped. It is a
  *positive* signal — an empty hub, or one holding only authored `.md`, still gets its README; an
  unreadable `.md` is itself a skip signal (never risk writing into content we couldn't inspect). See
  `specs/014-create-readme-skip-external/`.

### Docs
- The `elevating-your-link-gate` recipe now covers **directory links** and the gate-version coupling:
  an older `darnlink` treats a robust directory link as *broken* and repairs it into `README.md`, so a
  gate that touches directory links must be **≥ 0.8.0** (#21).

## [0.9.1] — 2026-07-22

### Fixed
- **`darnlink check` no longer crashes on a Windows cp1252 console.** The summary line printed `→`
  (U+2192), which the Spanish-Windows default code page (cp1252) cannot encode → `UnicodeEncodeError`
  → the gate exited non-zero on *encoding*, not on links (a false red for every Windows repo running
  the gate). The arrow is now ASCII `->`, and `main()` makes stdout/stderr degrade unencodable output
  instead of raising, so the gate can never crash on a console encoding again.

## [0.9.0] — 2026-07-22

Cross-repo **web-link** robustness lands as an opt-in adjunct, and the core becomes **web-aware**.

### Added
- **`web-check` subcommand (EXPERIMENTAL, opt-in, off by default)** (feature 013). Anchors and
  verifies **cross-repo web links** — a Markdown link to a `https://github.com/owner/repo/blob/…` file
  in *another* repository — against the destination's frontmatter `uuid`. `web-check PATH --online`
  fetches each destination (GitHub Contents API, stdlib `urllib`, no new dependency), reading the uuid
  to **anchor** a plain link (`--write`) or **verify** an anchored one (exit 4 on mismatch/404). Works
  **tokenless for public destinations**; a private destination without `$GITHUB_TOKEN` is reported
  `web_unverifiable` and never fails the build. Nothing runs without `web-check` *and* `--online`. See
  `specs/013-web-robustness/` and `docs/elevating-your-link-gate.md` §8.

### Changed
- **Core is now web-aware (strict improvement).** The core's repair/check ignore web links entirely
  (`is_web_href` guard): before, an anchored web link was wrongly reported `unresolvable`. Web anchors
  use a distinct `<!-- web-uuid: X -->` marker (never the core's `<!-- uuid: X -->`), so a core gate in
  any repo stays green next to a cross-repo web link.
- **Constitution v1.1.0**: Principle IV gains a single sanctioned network carve-out for the opt-in
  `web-check --online`; the default path and core stay offline and deterministic.

## [0.8.0] — 2026-07-22

First release with **directory links** — a robust link can now target a folder, not just a `.md` file.

### Added
- **Directory links** (feature 011). A robust link may point at a **directory**; the folder's identity
  is the `uuid` of its `README.md`. Disambiguation is by the href alone — a path ending in `.md` is a
  *file* link, any other path a *directory* link — so it is deterministic and needs no disk access to
  classify. Robustify anchors a directory link to its README's uuid; repair heals it to the folder's
  new location when it moves (kept a directory path, trailing slash). See `FORMAT.md` §4.1 and
  `specs/011-directory-links/`.
- **`--create-readme`** (feature 012). Opt-in: for a plain link to a directory that has **no**
  `README.md`, create one (a fresh uuid + a `# <dirname>` heading) so the link can be anchored. It
  never creates the directory itself, only a README inside an existing one; creates at most one README
  per directory; is dry-run by default; **respects `--exclude`** (never writes into an excluded
  subtree such as a mirror or vendored clone), `--only` and `--no-create-frontmatter-for`; and implies
  `--create-frontmatter`. Off by default, so the "never creates files" guarantee holds unless asked.
  See `specs/012-create-readme/`.

### Fixed
- The strict self-check (`darnlink . --robustify`) was failing on `main`: a prior commit gave
  `docs/elevating-your-link-gate.md` a `uuid` without robustifying its inbound links, so every branch
  inherited a red gate. Its 5 links are now anchored (#18).

## [0.7.1] — 2026-07-22

Recipe & docs only — **the CLI/package is byte-for-byte identical to 0.7.0**. This release exists so
the `recipes/` changes below live at a pinned tag that CI and hooks can fetch deterministically.

### Added
- **`recipes/darnlink-gate`: `mode=max`** — the fail-closed-links rung (`repair ⊂ check ⊂ max`). `max`
  gates integrity **+** strict **+** create-frontmatter, i.e. *a link to a file with no `uuid` fails
  the gate*. `check` has no create-frontmatter axis and the bare `--robustify --create-frontmatter`
  has no integrity axis, so `max` runs **both** dry-run passes (a true superset of `check`). Whole-repo
  only; the staged pre-commit stays at strict by design. Ported to `darnlink-gate.ps1`. See
  `docs/elevating-your-link-gate.md`.
- **`recipes/examples/`** — complete, copy-paste artifacts for all wall layers: `pre-commit` (staged),
  `pre-push` (whole repo — previously undocumented), a full GitHub Actions workflow and a Jenkinsfile
  stage (server wall, fail-closed). Not snippets to assemble.

### Fixed
- **`recipes/README.md` CI example was fail-**open**** — it ran `darnlink-gate` without
  `DARNLINK_GATE_FAIL_CLOSED=1`, so a copy-paste gave a green build that validated nothing. Documented
  fail-closed + exit 4, and the three-rung mode ladder. Playbook §6/§7 now cross-link the examples.

## [0.7.0] — 2026-07-22

### Added
- **`--only FILE` / `--only-from FILE` — scope writes to specific files** (feature 010). darnlink now
  separates the two scopes the positional `path` used to fuse: the **index** scope (which files are
  read — still the whole tree, so a link's target resolves wherever it lives) and the **write** scope
  (which files are modified). `--only` narrows the latter; `--only-from` reads the list from a file or
  stdin (`-`), so a caller can pipe `git diff --cached --name-only` in without darnlink learning about
  git. This makes the common "anchor the links in the file I'm committing, touch nothing else" case
  possible — previously you either scanned your subtree (and the tool couldn't see out-of-subtree
  targets, so it anchored nothing) or ran repo-wide (and rewrote everyone's links).
- **`--no-target-writes`** — with `--only`, refuse the one write that otherwise lands outside the
  scope (adding a `uuid` to a *target* so a link can be anchored). Links that would need it stay plain
  and are reported; the guarantee becomes absolute: **no** file outside `--only` is touched.
- **New finding kinds** in human and `--json` output: `out_of_scope`, `target_uuid_write`,
  `target_write_refused`. `--json` gains `write_scope` and `suppressed_outside_write_scope`.

### Fixed
- **`out_of_scope` no longer misreported as `no_frontmatter`.** A plain link whose target exists but
  was never scanned (outside `path`, or excluded) used to be reported as "target has no frontmatter"
  — stating as fact something the run never checked. It now has its own kind and an honest message.
  This is the confusion that motivated feature 010.

## [0.6.0] — 2026-07-21

### Added
- **Published on PyPI** — darnlink is now installable from the index, so the one-liner drops the
  `--from git+…` scaffolding: `uvx darnlink <folder>` (or `pipx install darnlink`). Lower friction
  and a proper package page instead of a bare repo URL.
- **PyPI packaging metadata** — `classifiers` (license, supported Python versions, topics) and
  `[project.urls]` (Homepage, Repository, Issues, Changelog), so the package is categorised,
  searchable and links back to the project.
- **Release automation via PyPI Trusted Publishing (OIDC)** — `.github/workflows/publish.yml` builds
  the sdist + wheel, runs `twine check`, and uploads on a published GitHub Release. **No API token
  is stored anywhere.**
- **`recipes/darnlink-gate`: modo FAIL-CLOSED** (`DARNLINK_GATE_FAIL_CLOSED=1`, o `"fail_closed": true`
  en `darnlink-gate.json`). La receta falla **abierta** por defecto —correcto en pre-commit: un commit
  offline no debe quedar bloqueado— pero eso **en CI es peligroso**: el gate *es* el muro, y un fallo
  transitorio de red/PyPI daba **build VERDE con cero ficheros validados**. Con el flag, esos casos
  salen con código **4** (distinguible de los hallazgos: `2` integridad, `3` strict). Actívalo siempre
  en CI. Detectado por una revisión adversarial de la propia receta.

### Fixed
- **Docs: stale version pins.** The README's quality-gate examples still pinned `rev: v0.1.1` /
  `rev: v0.2.0`, and the Status section said "Early (v0.1.0)". Anyone copy-pasting the gate got a
  release from before the strict gate existed.

## [0.5.0] — 2026-07-18

### Added
- **`recipes/darnlink-gate`** — a ready-made, config-driven gate wrapper (bash + `.ps1`), shipped as a
  **reference recipe** (not part of the CLI/package — the tool stays "links & UUIDs only"). It runs
  **both** checks, scopes to staged files in pre-commit vs the whole repo in CI, pins the darnlink ref,
  and fails open on network — so a repo wires darnlink into its gate with a tiny `darnlink-gate.json` +
  a 3-line hook instead of a bespoke wrapper that drifts. It lives in the **public** repo so any CI can
  fetch it **without a token**. See `recipes/README.md`.
- The recipe's `mode=repair` gates on **integrity only** — it always runs `darnlink check` (stable
  `0/2/3` contract) but treats a strict-only failure as clean, on both repo and staged scope.

## [0.4.0] — 2026-07-17

### Added
- **`--exclude` now takes a glob** (`fnmatch`, case-sensitive), not just an exact name — so a repo can
  skip a whole family in one declarative line instead of listing every directory and letting the list
  drift: `--exclude old --exclude 'old_*' --exclude '*_old' --exclude '*.old'`. **Backward-compatible**:
  a pattern with no wildcards matches exactly, so every existing `--exclude NAME` is unchanged. Spec
  `009-glob-excludes`.

## [0.3.0] — 2026-07-17

### Added
- **`darnlink check` — a report-only gate subcommand.** Runs **both** axes in one invocation — repair
  (integrity: broken/unresolvable robust links + invalid frontmatter) and robustify (strict:
  anchorable plain links left un-anchored) — and exits with a **distinguishable code**: `0` clean, `2`
  integrity failure, `3` strict-only failure (integrity takes precedence when both fail). It never
  writes. This closes the "strict is not a superset of repair" trap: a gate that ran only
  `--robustify` was blind to broken robust links, and vice-versa; `check` can't forget a half. darnlink
  *checks and reports* — the consumer (CI/hook acting on the exit code) is what *gates*. Spec
  `007-darnlink-check`.

## [0.2.0] — 2026-07-17

### Added
- **`<!-- darnlink-ignore-links -->` — a source-only opt-out.** darnlink never rewrites the links
  *inside* a file carrying it (neither robustified nor repaired), but the file stays a first-class
  **target**: its `uuid` is still indexed, so inbound robust links keep resolving and still heal when
  it moves. This is what a **generated** file needs — its generator rewrites it wholesale, so
  anchoring inside it is churn, yet a generated `INDEX.md` is usually the file everything links *to*.
  `<!-- darnlink-ignore-file -->` could not serve that case: it drops the file from the graph on both
  axes, taking inbound links down with it, so projects worked around it with external allowlists —
  which darnlink cannot honour, so `--robustify --write` wrote into those files anyway and the
  workaround could only complain afterwards. Put the marker **after** the frontmatter (a marker on
  line 1 hides the file's own `uuid`). Reported as `link-ignored` / kind `ignored_links` and listed
  under `link_ignored_files` in `--json`; a strict `--robustify` gate passes on a tree whose
  generated files carry it. Documented in FORMAT.md §5; spec `006-ignore-links-marker`.
- **Strict, fail-closed gate** — a first-class way to require that every *anchorable* link is robust,
  not just that existing robust links keep working. Run `darnlink . --robustify` (dry-run: it reports
  and exits non-zero, it does not write) or wire the new `darnlink-strict` pre-commit hook id. A target
  is anchorable when it's a local file with frontmatter; targets that can't take a `uuid` (non-local,
  deny-listed, or without frontmatter unless `--create-frontmatter`) are left alone. Exempt generated
  files with `<!-- darnlink-ignore-file -->` or `--exclude`. Documented in the README ("Stricter:
  require every link to be robust"); darnlink now dogfoods it in its own CI and `tools/check.sh`.

## [0.1.1] — 2026-07-11

### Fixed
- A UTF-8 BOM before the frontmatter no longer hides a file's `uuid` from the index. Previously the
  index reader used plain `utf-8`, so the BOM sat before `---` and the target's `uuid` was never
  indexed — inbound robust links to a BOM-carrying target were left unresolved instead of repaired.
  Common on Windows-authored files; found by validating on real Windows.

### Changed
- CI now runs the full test suite **and** the one-liner smoke test on Windows as well as Linux
  (`windows-latest` in the matrix), so Windows-specific regressions are caught automatically.

## [0.1.0] — 2026-07-11

First public release.

### Added
- **Repair**: fix robust Markdown links whose target moved or was renamed, matched by the target's
  `uuid` (exact match — no heuristics, no network).
- **Robustify**: upgrade a plain relative link to a robust one — anchor it to the target's `uuid`
  (added to the target's frontmatter if missing) via an inline `<!-- uuid: … -->` comment.
- **Conflict detection**: when a link's path still resolves but its anchored `uuid` points elsewhere,
  report a conflict instead of silently rewriting the path.
- CLI: dry-run by default; `--write` to apply; `--robustify`, `--create-frontmatter`,
  `--exclude`, `--ignore-block`, `--no-create-frontmatter-for`, `--json`.
- Cross-platform I/O: preserves original line endings (CRLF/LF); reads UTF-8 with BOM.
- Ships a [pre-commit](https://pre-commit.com/) hook (`darnlink`, `darnlink-repair`).
- Format specification: [FORMAT.md](FORMAT.md) <!-- uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef -->.

[Unreleased]: https://github.com/txemi/darnlink/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/txemi/darnlink/releases/tag/v0.5.0
[0.4.0]: https://github.com/txemi/darnlink/releases/tag/v0.4.0
[0.3.0]: https://github.com/txemi/darnlink/releases/tag/v0.3.0
[0.2.0]: https://github.com/txemi/darnlink/releases/tag/v0.2.0
[0.1.1]: https://github.com/txemi/darnlink/releases/tag/v0.1.1
[0.1.0]: https://github.com/txemi/darnlink/releases/tag/v0.1.0
