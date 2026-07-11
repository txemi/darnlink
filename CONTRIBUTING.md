# Contributing to darnlink

Thanks for your interest! darnlink is small on purpose — it does two things (repair and robustify
Markdown links anchored by UUID) and tries to stay disciplined about scope.

## Scope discipline

darnlink only knows about: `.md` files, links, and a `uuid` field in YAML frontmatter. It has **no**
notion of issues, projects, entity types, profiles, or autogrid. Please keep PRs within that scope —
features that turn darnlink into a docs/project manager are out of scope by design.

Core principles (see `.specify/memory/constitution.md`):

- **Dry-run by default**, `--write` to apply.
- **Deterministic** — exact UUID match, no heuristics, no network.
- **Idempotent**, and **no database / no index file**.

## Dev setup

Requires Python 3.13.

```bash
uv venv --python 3.13 .venv
uv pip install -e ".[dev]"
```

## Tests & quality gate

```bash
tools/check.sh        # mirrors CI: runs the test suite + checks
# or directly:
uv run pytest
```

CI (`.github/workflows/ci.yml`) runs on every PR; please make sure it's green. A local
`hooks/pre-commit` is available — activate it with `bash setup.sh` (sets `core.hooksPath`).

## Pull requests

- Branch off `main`, keep PRs focused, and add a test for any behavior change (the project is
  test-first).
- Don't widen scope (see above). If unsure whether something fits, open an issue first.
- The robust-link format is specified in [FORMAT.md](FORMAT.md) <!-- uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef --> — it's tool-agnostic, so changes to
  the format are a bigger deal than changes to the tool; discuss them first.

## License

By contributing you agree your contributions are licensed under the
[GNU GPL v3.0-or-later](LICENSE).
