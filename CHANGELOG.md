# Changelog

All notable changes to darnlink are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **The English-only gate now covers the surfaces that are actually published**: commit messages,
  PR titles/descriptions, issues, and `.md` documentation. Until now it judged one thing —
  comment lines in `.py` files — while the rule it enforces has always covered far more. The gap was
  not theoretical: with the gate green and the tree at zero, this public repo carried **2 of 2 open
  issues written entirely in Spanish, 4 Spanish PR titles and 7 Spanish commit subjects on `main`**.
  Files were the only surface anybody had wired, so files were the only surface that stayed clean.

  New `lang_gate.py --prose FILE|-` judges free text (fenced blocks, inline `code` and URLs are
  exempt, so pasting real output is safe), wired into four places: `hooks/commit-msg`, a CI step over
  every commit a PR adds, a CI step on the PR title and body, and `.github/workflows/lang-issue.yml`.

  **The issue surface cannot block and does not pretend to** — GitHub has no pre-publication hook for
  issues, so that workflow labels `needs-english` and comments once. Worth knowing when you write
  one: it tells you *after* the text is public.

### Fixed
- **`.md` prose was unjudgeable by construction.** The tree scan applied the Python rule to every
  file, and that rule rejects any line containing `:` or `(` as "code" — which is most of a written
  paragraph. Markdown is now judged with its own rule (everything is prose except fenced blocks),
  which immediately surfaced five Spanish lines in this file, sitting under a green gate since
  v0.6.0. Translated here; the baseline stays pinned at 0.

## [0.20.4] — 2026-08-10

### Added
- **`darnlink-gate`: `dangling_max`, a budget that makes the `repo` rung adoptable before you reach
  zero** (#47). The `dangling` axis had four rungs and a hole between the last two. `added-lines` —
  the adoption rung — **needs a staged diff**, so it only ever bites on `scope=staged`. On a
  whole-repo surface (pre-push, CI) there is no diff to judge and it degrades to `warn`.

  The consequence is worth stating plainly: **a repo carrying old dangling debt has no server-side
  wall for this axis, on any surface, until the day it reaches exactly zero.** Measured on a
  consuming repo: the axis had been "on" for months, its only wall a local hook that itself fails
  open when `uv` is missing. That is not a wall, it is a habit — and raising the setting was no
  escape, because `repo` demands zero and the repo was at 256.

  `"dangling_max": <int>` (default `0`) turns `repo` into a budget: fail only above that count. You
  get the wall **today**, at your current number, and every cleanup lowers it. Same shape as a
  coverage floor — the number is a receipt of where you are, not permission to stay.

  Three details keep it a ratchet rather than an allowance:

  - **Coming in under budget is reported**, and *reaching zero especially so* — a budget nobody
    lowers **is** an allowance, and nothing else in the system can notice it went stale. The
    reminder has to appear in front of whoever just did the cleanup: the one moment someone is both
    looking and able to act.
  - **A non-numeric value counts as `0`, never as infinite.** Silently *widening* an allowance is
    the one direction a config typo must not be able to go.
  - **Absent key = byte-identical verdict.** Raising the pin changes nothing for anyone who did not
    opt in — the rule the whole axis was built on.

  The zero case was missing from the first draft and caught in review: the verdict lived inside the
  *there are findings* branch, so the gate went **silent exactly when the last dangler died**. A
  ratchet whose reminder disappears on success is an allowance with a grace period. Its regression
  test was validated by failing it against the previous recipe.

## [0.20.3] — 2026-08-10

### Fixed
- **`darnlink-gate`: the `web` pass exited the script, skipping every axis after it** (#45). It ended
  in a bare `exit "$rc"`, which left the recipe *before* the `create-readme` axis further down. In a
  repo configured with `mode=max` + `web: true` + `create_readme_excludes`, **that axis therefore
  never ran**: the config said it was on, the gate answered `exit 0`, and a directory link to a
  folder with no README sailed straight through. Measured on two consuming repos before the fix —
  same tree, same config, `web` on → `0`, `web` off → `1`. One of them had spent half a day with the
  axis nominally enabled and gating nothing.

  The `exit` was not gratuitous and what it protected is preserved: `web-check`'s codes are all in
  `0..4` and **none of them means "could not run"**, so they must not pass through the
  `rc>3 → bail` heuristic, which would read a genuine `4` (broken public web link) as a network
  hiccup and go green. The verdict is now marked **already final** and the recipe falls through; the
  exit happens once, at the end, with the worst verdict.

  That immunity has a **ceiling**, missing from the first draft and caught in review: a code *above*
  the contract (`127` no `uvx`, `126` permissions) is not a verdict about the repo — the tool did not
  run — so `>4` always bails, keeping the fail-open promise. Without it, a machine without `uv` would
  have received a hard `127` from a gate that promises to fail open.

  Three regression tests, each validated by failing on the previous code: the axis still runs with
  `web` on, falling through does not downgrade a web failure, and a `127` during the web pass still
  skips (fail-open) or exits `4` (fail-closed).

## [0.20.2] — 2026-08-09

### Fixed
- **`darnlink-gate`: the command the failure message tells you to paste no longer rewrites the whole
  repo under a different policy** (#40). The staged gate used to suggest a bare
  `darnlink . --robustify --write`: correct as a capability, a trap as advice. It touches every file
  in the tree, and it does **not** carry the `--exclude` list the gate that just failed you was
  configured with — so it applies a different policy than the one that produced the error. Measured
  in a consuming monorepo: **110 links anchored across 26 files when one was asked for**, pasted by
  someone who trusted the message, on a tree shared by several concurrent sessions. The suggestion is
  now the piped `--only-from -` form (scan the repo, write only the staged files), carries the run's
  own `--exclude`/`--ignore-block` shell-quoted, spells out `--create-frontmatter` (without it the
  target keeps no uuid and the anchor silently never appears), and says explicitly not to run the
  bare form.

### Changed
- **The example config in `recipes/darnlink-gate` is the strict target, not a stale minimum** (#42).
  It had sat at `v0.7.0` for thirteen releases while recommending `mode: check` with no `dangling`
  key — an axis this very file implements. It now shows every axis at its strictest, plus a six-rung
  **adoption path** (pasting the target into a never-gated repo fails on contact, and a gate that
  fails on arrival gets deleted rather than climbed) and a sub-ladder for `dangling`.
  The `ref` is deliberately a **`vX.Y.Z` placeholder** with the command that resolves it: any
  concrete pin written into a comment ages the moment it is committed, which is exactly how this
  example drifted. Documented too: `dangling: added-lines` needs a staged diff, so it only bites
  under `scope=staged` — on a whole-repo surface it degrades to `warn`, and `repo` is the only rung
  with server-side enforcement.

### Added
- **English-only ratchet gate for this repo's own sources** (`tools/lang_gate.py`, wired into CI and
  `tools/check.sh`). New and modified lines must be English; legacy lines live in a per-file baseline
  whose counts can only decrease. Escape hatch for a false positive: `# lang-ok`.

## [0.20.1] — 2026-08-09

### Fixed
- **`darnlink-gate`: the staged scope crashed on any repo whose `check --json` exceeded 128 KiB.**
  Linux caps a *single* environment variable at `MAX_ARG_STRLEN` = 32 pages = **128 KiB** — a
  per-string limit, separate from the ~2 MB `ARG_MAX` total — and exceeding it makes the next `exec`
  fail with `E2BIG`. The staged path exported the whole JSON payload, so on a real consumer (~200 KB)
  the gate did not report a finding, it **crashed**: `sed: Argument list too long`, exit 126. A gate
  that cannot run gates nothing, and it fails *loudly* only if someone is watching the output.
  Payloads (findings JSON, staged list, added-lines map) now travel through temp files, cleaned up by
  an `EXIT` trap; only short paths go through the environment. `create_readme_offenders` already did
  this for the same reason — the staged path did not, and only tipped over once the JSON grew.
  Pinned by a regression test whose scenario produces a ~547 KB payload.


## [0.20.0] — 2026-08-09

### Added
- **The `dangling` axis is now gateable, opt-in, with an added-lines ratchet** (`recipes/darnlink-gate`).
  `dangling` defaults to **`off`**, so upgrading the pin changes no verdict anywhere; `warn` lists
  without failing; **`added-lines`** fails only on findings on lines the commit *adds* (`scope=staged`);
  `repo` fails on any. Per-file gating was tried and rejected — touching one line of a README that
  already carries old danglers would block the commit, which pushes people to `--no-verify`, and a gate
  people bypass gates nothing. The added lines come from `git diff --cached -U0`: git lives in the
  recipe, not in darnlink (spec 008, Option B).
- **`Finding.line`** — optional, defaulted, set only by `dangling` today, and surfaced in
  `check --json`. It exists because a *consumer* needs it as data: the ratchet intersects findings with
  the lines a commit adds, and scraping that out of `detail` would couple the gate to prose.


- **`dangling`: a plain link whose target does not exist is now reported** (feature 015). It was
  invisible before — not `unresolvable` (that is a *robust* link whose uuid died) and not
  `robustify` (there is nothing to anchor). `_anchor_target` returned `None` both for "the target is
  not anchorable" and for "the target is not there", and the caller could not tell them apart, so a
  link pointing at nothing appeared in no category at all, not even a tolerated one. Measured across
  nine repositories that all gate on darnlink: **3,212 such links**, none of them named by any mode.
  The trigger was a documentation reorganisation that moved 78 Markdown files in one commit and left
  every axis green.
  - **Report-only.** No mode, including `--write`, acts on it. Determinism is unaffected: a
    filesystem existence check is exact and offline.
  - **It does not move any exit code.** `check` reports it on its own axis (and in `--json` under
    `dangling`), deliberately outside `exit_code`: folding it in would turn every consumer's gate red
    on upgrade, whose only escape would be *lowering* its mode — a relaxation, in a ladder designed
    to only tighten. Which findings gate stays the caller's policy.
  - The target's **extension is irrelevant**; only its existence. A target that *exists* but is not
    anchorable (a `.png`, a README-less directory) is still not reported, and anchoring remains
    `.md`-only. Image embeds count (FR-050).
  - Composes with everything that already silences a link: code spans and fences, `--ignore-block`
    regions, `darnlink-ignore-links` and `darnlink-ignore-file`. Percent-encoded paths are accepted
    in their decoded spelling, so `my%20file.md` next to `my file.md` is not a false alarm.

### Changed
- **`check` no longer enumerates dangling findings in its text output** — it states the count on one
  line and carries the details in `--json`. On the trees this axis lands on (thousands of dead links in
  the repos it was measured on) one line each buried the findings that actually gate the build. The
  count keeps it honest; the gate recipe prints them when its axis is switched on.

### Known gaps
- `darnlink-gate.ps1` ignores the `dangling` key, so a Windows-only gating surface does not enforce
  this axis yet.

## [0.19.2] — 2026-08-08

> **Never tagged.** No `v0.19.2` release exists: the next release commit went straight to
> `0.20.0`, so this fix shipped inside **v0.20.0**. The section is kept because the change is
> real and dated; the version number is not. Its link below points at the commit, not a tag.

### Fixed
- **`--robustify --write` no longer duplicates a uuid comment that is already on the line, just
  detached from its link.** The grammar accepts only whitespace between the link's `)` and its
  `<!-- uuid: … -->`, so one token of inline markup in between — a closing `**` is the usual way to
  get this wrong — leaves the comment attached to nothing while *looking* attached to a reader. The
  link is therefore still plain, and robustify appended a **second** comment carrying the same uuid.
  The file ended up with the uuid twice, one copy anchoring nothing, and because the link was robust
  afterwards every later run reported the tree **clean**: the litter became permanent and silent —
  the exact failure Constitution II exists to prevent. Robustify now **moves** such an anchor into
  place instead of cloning it, and only when the file leaves no room for doubt: exactly one such
  stray **trailing** the link on that line, and exactly one link that could claim it. The
  after-the-link condition is the mechanism itself — a comment that fell out of the grammar was by
  definition trailing the `)`; one placed *before* the link got there by hand, for some other reason.
  A stray sitting **before** the link therefore neither blocks the move nor is touched by it: it is
  left in place and reported, because it was never a candidate to begin with.
  Anything else is left untouched — guessing whose anchor it is would be a heuristic (Constitution
  IV) — but it is announced in the finding, never silently duplicated. Tests in
  `tests/test_detached_anchor.py`.
- **The report now says why an apparently-anchored link is still reported as plain.** The old detail
  read `path/to/target.md +uuid <X>` while `<!-- uuid: X -->` was plainly visible on that same line,
  which reads as a tool bug and sends the reader looking in the wrong place; it cost a repository a
  blocked `pre-push` gate before the cause was understood. The finding now names the detached anchor
  and what happened to it — moved, or left alone with the reason.

## [0.19.1] — 2026-08-07

### Fixed
- **`web-check`: the text report no longer prints one line per `web_unverifiable` finding.** It lists
  the first `UNVERIFIABLE_PREVIEW` (20) and then a `... and N more` line. `web_unverifiable` is
  informational — it never fails the exit — so on a documentation repo whose Markdown holds a few
  thousand ordinary external links (docs sites, videos, intranet URLs: anything that is not a GitHub
  blob/raw URL) the old report emitted thousands of lines. Two consequences, both fixed: the
  actionable `web_mismatch` / `web_not_found` lines were buried in the noise, and a caller reading
  the output through a pipe could be flooded — in a `pre-push` git hook, whose stdio is a
  non-blocking pipe, the run died with `BlockingIOError: write could not complete without blocking`,
  so a phase that had found **nothing wrong** (`exit 0` when run standalone) blocked every push in
  the repo until `--no-verify` was used. Nothing is silenced (Constitution II): the full total stays
  in the summary line and `--json` still carries every finding. `web_mismatch`, `web_not_found` and
  `web_anchor` are still listed in full — they are actionable and they do fail the exit. Tests in
  `tests/test_weblinks.py`.

## [0.19.0] — 2026-07-30

### Changed
- **`recipes/darnlink-gate`: the create-readme axis now works under `mode=check`/`repair` (not only
  `mode=max`), and gained a per-axis `create_readme_excludes` key — for repos with a big `mirrors/`
  tree.** With `create_readme: true`, a plain link to a folder with no README now fails the gate under
  any mode: it runs as its own dry-run pass filtered to the `create_readme` findings (reusing the
  staged scope's JSON-by-kind filter). The new `create_readme_excludes` (default `[]`) layers extra
  directory globs **onto the create-readme pass only**, so a repo can skip README-creation under an
  external mirror (we don't invent a README for someone else's export) **without** dropping the mirror
  from the integrity/robustify axes — inbound links into the mirror still validate. Fully backward
  compatible: `mode=max` with no `create_readme_excludes` keeps the old folded behavior byte-for-byte;
  the key absent = empty. Recipe-only change — the darnlink CLI is untouched. Tests in
  `tests/test_recipe_gate.py`.

## [0.18.0] — 2026-07-29

### Added
- **Reusable GitHub Action (`action.yml`) — adopt darnlink in CI in one line.** Other repos can now
  gate their Markdown links with `- uses: txemi/darnlink@v1` instead of hand-writing a `uvx darnlink`
  step. Composite action: installs `uv`, runs `darnlink` over `path` (default `.`), report-only by
  default (fails the build if a link needs repair). Inputs: `path`, `args` (passthrough, e.g.
  `--robustify` for fail-closed strict mode, `--write` to auto-repair), `version` (pin darnlink from
  PyPI for reproducible CI). Mirrors the existing pre-commit hook so both ecosystems get one-line
  adoption; also lists darnlink on the GitHub Marketplace. README "quality gate" section updated.

## [0.17.0] — 2026-07-27

### Fixed
- **`web-check --online`: a 404 in a repo the token CANNOT access is now `web_unverifiable`, not
  `web_not_found`.** With a token, 0.16.0 called every 404 a real break — but a link to a **private
  cross-org repo** (e.g. a client org our read-only PAT has no access to) 404s because we cannot see it,
  not because the file moved. Now, on a 404 with a token, `default_fetcher` does one extra probe — `GET
  /repos/{owner}/{repo}` — and only calls the 404 a break if the destination **repo is readable**;
  otherwise it returns the sentinel `-2` → `web_unverifiable`. The repo probe is cached per
  `(owner, repo, token)` (a repo linked N times is checked once) and falls back to the plain
  404-is-broken behaviour on a network blip. This lets `web: true` run on repos that link to
  client/third-party orgs (one consumer repo has ~1400 links into an org it cannot read) without a wall of false breaks.
  Pairs with the token-gated 404 (0.16.0) and the transient-retry (0.15.0).


## [0.16.0] — 2026-07-26

### Fixed
- **`web-check --online`: a 404 without a token is now `web_unverifiable`, not `web_not_found`.**
  GitHub returns **404** (not 403) for a **private** repo the caller can't see — indistinguishable from a
  genuinely moved/deleted file. Classifying every 404 as a break made a **tokenless** run (a dev machine,
  a CI job or a git hook without the PAT) **false-fail on every private cross-repo link** — the real-world
  "false breaks" that blocked pushes across sessions. Now the 404 verdict is gated on token presence:
  - **with a token** → `web_not_found` (a 404 is trustworthy → **fail-closed**, exit 4);
  - **without a token** → `web_unverifiable` (ambiguous → **does not fail**, exit 0).
  This is the "fail-closed **only when there is a token**" contract: a tokened gate (CI/Jenkins with a RO
  PAT) catches real breaks; a tokenless clone never false-reds. Public-repo breaks are still caught by any
  tokened surface. Pairs with the recipe reading `$GITHUB_TOKEN` from `~/.config/github_token_ro` (0.14.0).

## [0.15.0] — 2026-07-26

First **code** change since 0.12.0 (0.13/0.14 were recipe-only).

### Fixed
- **`web-check --online`: transient GitHub responses no longer produce a false `web_not_found`.**
  `default_fetcher` now RETRIES transient statuses with short backoff (0.5s → 1.0s → …, capped 4s,
  3 attempts by default). The transient set includes **404** on purpose: the Contents API returns 404
  under secondary-rate-limit and for a file requested right after its push (CDN not yet warm) — a false
  break that would fail a **blocking** gate (pre-commit / pre-push) for a link that is actually fine.
  429/5xx/network-error are the usual throttle/outage cases. A **genuinely** dead link still 404s on
  every attempt, so it is reported exactly as before — retry removes only the flake, never hides a real
  break. Tune with `DARNLINK_WEB_ATTEMPTS` (default 3; 1 disables retry). This makes `web: true` safe to
  run in blocking local gates, not just CI/manual.

## [0.14.0] — 2026-07-23

Recipe & docs only — **package byte-for-byte identical to 0.12.0**.

### Added
- **Recipe `darnlink-gate`: the `web` pass reads `$GITHUB_TOKEN` from a read-only PAT file** when it is
  not already in the environment (default `~/.config/github_token_ro`, override `DARNLINK_GATE_TOKEN_FILE`).
  A git hook's environment usually lacks `GITHUB_TOKEN`, so without this, turning `web` on in a repo with
  **private** cross-repo destinations would 404 them and read them as broken. Missing file → private
  destinations stay `web_unverifiable` (non-fatal), exactly as before. Bash + PowerShell.

## [0.13.0] — 2026-07-23

Recipe & docs only — **the CLI/package is byte-for-byte identical to 0.12.0**.

### Changed
- **Recipe `darnlink-gate`: the `web` pass now passes the repo's `excludes` to `web-check`** (not only
  `ignore_blocks`). `web-check` gained `--exclude` in 0.12.0; without wiring it, turning `web` on in a repo
  that vendors clones/mirrors made `web-check` fetch (and with `--write` anchor) web links *inside* someone
  else's checkout. Now it skips them, exactly like the core does. Wired in the bash and PowerShell recipes.

## [0.12.0] — 2026-07-23

### Added
- **`web-check --exclude PATTERN`** — `web-check` scanned the whole tree with no way to skip
  directories, so in a repo that vendors clones of foreign repos it would fetch and (with `--write`)
  anchor web links *inside* those clones, injecting `web-uuid` markers into someone else's checkout.
  `--exclude` (same dir-name-glob semantics as the other commands) skips them — needed to turn the
  `web` recipe key (0.11.0) on in any repo with a `clones/` tree (#23).

## [0.11.0] — 2026-07-23

Recipe & docs only — **the CLI/package is byte-for-byte identical to 0.10.0**. This release exists so
the `recipes/` changes below live at a pinned tag that a fleet's CI and hooks can fetch deterministically.

### Added
- **Recipe `darnlink-gate` gains two opt-in `darnlink-gate.json` keys** (both `mode=max` only), so a
  fleet can turn them on by config instead of hand-wiring each repo:
  - **`"web": true`** — adds a `web-check --online` pass: cross-repo Markdown links to other GitHub
    repos must resolve to the destination file's `uuid`. Public targets are tokenless; private ones
    send `$GITHUB_TOKEN` if set, else report `web_unverifiable` (a warning, never a failure). Fail-closed
    on a broken public web link. The recipe exits web-check's code directly (its `4` is a real broken
    link, not the core's `rc>3` "unreachable" — which would otherwise swallow it and go green).
  - **`"create_readme": true`** — the `max` robustify pass also runs `--create-readme`, so a directory
    link whose target folder has no README (no `uuid` to anchor) fails the gate (dry-run detects it).
  Both wired in the bash and PowerShell recipes. `DARNLINK_GATE_WEB` / `DARNLINK_GATE_CREATE_README`
  env overrides mirror the existing ones.

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
- **`recipes/darnlink-gate`: FAIL-CLOSED mode** (`DARNLINK_GATE_FAIL_CLOSED=1`, or `"fail_closed": true`
  in `darnlink-gate.json`). The recipe fails **open** by default — right for pre-commit, where an
  offline commit must not be blocked — but that is **dangerous in CI**: there the gate *is* the wall,
  and a transient network/PyPI failure produced a **GREEN build with zero files validated**. With the
  flag those cases exit with code **4**, distinguishable from findings (`2` integrity, `3` strict).
  Always turn it on in CI. Found by an adversarial review of the recipe itself.

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

[Unreleased]: https://github.com/txemi/darnlink/compare/v0.20.4...HEAD
[0.20.4]: https://github.com/txemi/darnlink/compare/v0.20.3...v0.20.4
[0.20.3]: https://github.com/txemi/darnlink/compare/v0.20.2...v0.20.3
[0.20.2]: https://github.com/txemi/darnlink/compare/v0.20.1...v0.20.2
[0.20.1]: https://github.com/txemi/darnlink/compare/v0.20.0...v0.20.1
[0.20.0]: https://github.com/txemi/darnlink/compare/v0.19.1...v0.20.0
[0.19.1]: https://github.com/txemi/darnlink/compare/v0.19.0...v0.19.1
[0.19.0]: https://github.com/txemi/darnlink/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/txemi/darnlink/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/txemi/darnlink/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/txemi/darnlink/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/txemi/darnlink/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/txemi/darnlink/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/txemi/darnlink/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/txemi/darnlink/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/txemi/darnlink/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/txemi/darnlink/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/txemi/darnlink/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/txemi/darnlink/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/txemi/darnlink/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/txemi/darnlink/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/txemi/darnlink/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/txemi/darnlink/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/txemi/darnlink/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/txemi/darnlink/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/txemi/darnlink/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/txemi/darnlink/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/txemi/darnlink/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/txemi/darnlink/releases/tag/v0.1.0
[0.19.2]: https://github.com/txemi/darnlink/commit/f0cf814
