# Quickstart — darnlink

## Install / run (one command)

```bash
uvx darnlink            # run without installing (ephemeral)
# or
pipx install darnlink
```

## The two operations

```bash
# REPAIR — fix robust links whose target moved (UUID-anchored)
darnlink                 # dry-run report over the current dir (writes nothing)
darnlink path/to/repo    # report over a specific dir
darnlink --write         # apply the repairs

# ROBUSTIFY — upgrade plain links to robust ones
darnlink --robustify                       # dry-run report
darnlink --robustify --write               # apply (adds the UUID anchor)
darnlink --robustify --write --create-frontmatter   # also create frontmatter where missing
```

Safe by default: nothing is written unless `--write` is passed. Exit code is non-zero when links
need repair (or are unresolved), so it works as a CI gate.

## The robust-link format

```markdown
[link text](relative/path.md) <!-- uuid: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx -->
```
(`xxxx…` stands for a real UUID, e.g. `123e4567-e89b-42d3-a456-426614174000`.)

The same UUID lives in the target file's YAML frontmatter:

```markdown
---
uuid: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
---
```

When the target moves, `darnlink` finds it by UUID and rewrites the path. The link stays a normal
clickable Markdown link; the UUID is an invisible HTML comment.

## As a pre-commit hook

```yaml
# .pre-commit-config.yaml
- repo: https://github.com/<owner>/darnlink
  rev: v0.1.0
  hooks:
    - id: darnlink          # fail if any robust link is broken
    # - id: darnlink-repair # or auto-fix
```

## As a GitHub Action

Run `darnlink .` in CI (see `.github/workflows/ci.yml`): the job fails if any robust link is broken.
