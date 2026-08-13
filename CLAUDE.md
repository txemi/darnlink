<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->

## Language: English only

darnlink is an open-source project intended to be published publicly. **Everything in this repo
is written in English** — code, comments, docstrings, documentation, spec files, commit messages,
**pull request titles/descriptions, and GitHub issues and their comments**. No exceptions,
regardless of the language used in the session chat.

**The enumeration above is not decoration: each surface names what enforces it.** Until 2026-08-11
the rule was stated exactly once and checked in exactly one place — `.py` comments — and the result
was that the file gate stayed green while the *published* surfaces filled up with Spanish: both open
issues, four PR titles, seven commit subjects on `main`. A rule that is only written down is a rule
that is only broken where nobody measures.

| Surface | What checks it | Can it block? |
|---|---|---|
| `.py` comments/docstrings, `.md` docs, file NAMES | `darnlang check` (`tools/check.sh`, `lang` CI job), pinned by `tools/darnlang_ref.sh` | yes — pre-commit, pre-push, CI |
| Commit message | `hooks/commit-msg` + the CI step, one message at a time | **conditionally** — the hook SKIPS when `uvx` is absent or the pin cannot be resolved (offline). CI is the wall that always runs |
| PR title / description | CI step in the `lang` job | yes — the merge is blocked |
| Issue title / body | `.github/workflows/lang-issue.yml` | **no** — GitHub cannot gate an issue before it is published, so it labels `needs-english` and comments once |

The last row is the one to internalise when writing: for an issue, **there is no wall to catch
you**. If you are about to open one from a session held in Spanish, translate it as you write it —
the automation can only tell you afterwards, in public.
