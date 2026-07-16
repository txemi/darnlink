# Changelog

All notable changes to darnlink are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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

[Unreleased]: https://github.com/txemi/darnlink/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/txemi/darnlink/releases/tag/v0.1.1
[0.1.0]: https://github.com/txemi/darnlink/releases/tag/v0.1.0
