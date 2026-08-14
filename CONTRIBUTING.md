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

**Everything in this repo is written in English** — code, comments, docstrings, docs, spec files,
commit messages, PR titles/descriptions, and issues. [`darnlang`](https://github.com/txemi/darnlang) enforces it on four surfaces, pinned by
`tools/darnlang_ref.sh`:

- **tracked files** — `.py`/`.pyi` (comments and docstrings only) and
  `.md`/`.markdown`/`.rst`/`.txt`/`.html`/`.htm`/`.jinja`/`.j2` (all prose except fenced code
  blocks). Config and CI files — `.yml`, `.toml`, `.sh`, `Jenkinsfile` — are **not** judged, so a
  comment in them is on you. `tools/check.sh` and the `lang` CI job. File NAMES are judged too;
- **commit messages** — `hooks/commit-msg`, plus a CI step over every commit the PR adds;
- **PR title and description** — a CI step, so a non-English title blocks the merge;
- **issues** — `.github/workflows/lang-issue.yml`. GitHub offers no way to gate an issue before it
  is published, so this one cannot block: it labels the issue `needs-english` and says so once in a
  comment. A report in another language is welcome and will be read as it stands — the label marks
  translation as pending, it is not a rejection.

The detector is a heuristic and can be wrong; silence a genuine false positive with a trailing
`# lang-ok` on that line (`<!-- lang-ok -->` in Markdown, where `#` is a heading). Code inside
fenced blocks, inline `code` spans and URLs are never judged, so pasting real output is safe.

## Pull requests

- Branch off `main`, keep PRs focused, and add a test for any behavior change (the project is
  test-first).
- Don't widen scope (see above). If unsure whether something fits, open an issue first.
- The robust-link format is specified in [FORMAT.md](FORMAT.md) <!-- uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef --> — it's tool-agnostic, so changes to
  the format are a bigger deal than changes to the tool; discuss them first.

### Automated review

This repo has **GitHub Copilot code review** enabled. When you open a PR, Copilot reviews it
automatically and leaves inline comments. Please address them before asking a human to merge: fix the
valid ones, and reply to any you're dismissing with the reason. It has a good hit rate here — on a
recent PR all four of its findings were real (two correctness, two performance).

Two gotchas worth knowing:

- **It reviews once, on open.** Pushing a fix does **not** trigger a re-review — you have to request
  one. In the GitHub UI: the *Reviewers* gear → re-request Copilot.
- **From the CLI, the REST endpoint silently ignores it** (Copilot is a bot, and
  `POST /pulls/{n}/requested_reviewers` only takes users — it returns 200 and does nothing). Use
  GraphQL with the bot's node id:

  ```bash
  # find the bot id from an existing review, then:
  gh api graphql -f query='mutation($pr:ID!,$b:[ID!]) {
    requestReviews(input:{pullRequestId:$pr, botIds:$b, union:true}) { pullRequest { number } } }' \
    -f pr='<PR node id>' -f b='<copilot bot node id>'
  ```

## Spec & branch numbering (avoid collisions)

Specs live in `specs/NNN-slug/` with a **contiguous, monotonic** number. The Spec Kit helper picks
the next number by scanning both `specs/` **and branch names** (local + remote, via `ls-remote`).
That only stays collision-free if every reservation is visible to the scanner, so:

- **Every feature branch carries the `NNN-` prefix** and is **pushed** — that is what lets the
  allocator see a number reserved on another branch and skip it. A spec numbered inside a branch
  whose *name* has no `NNN-` prefix is invisible, and the next feature will grab the same number.
- **Never "leave a gap"** by picking a high number by hand — it doesn't prevent collisions (two
  people picking high collide again), breaks the contiguous sequence the tooling assumes, and rots
  into confusing holes. Take the next number; let the scanner guarantee uniqueness.
- **Long-lived product lines are the one exception** to the `NNN-` branch rule (e.g. `darnlink-web`):
  they are lines, not features. Features *within* such a line still branch off it with `NNN-` names.

## License

By contributing you agree your contributions are licensed under the
[GNU GPL v3.0-or-later](LICENSE).
