# Changelog

All notable changes to darnlink are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Feature 017 — the read axis can see a diagram's `click` destinations** (`--include-mermaid`,
  recipe key `include_mermaid`). **Off by default, per repository.** A `mermaid` diagram carries
  its links in `click` directives, which live inside a fenced block: feature 002 hides them from
  every axis, including the read-only ones, so they die silently when a file moves and no gate ever
  notices. Measured on a real tree, one folder reorganisation killed 14 of a diagram's destinations
  at once while everything stayed green.

  - **The write operations are unchanged.** FR-015 is not amended: repair and robustify still
    ignore every link inside every fence. This is the read axis only.
  - **These links are never anchored** — they are report-only. The anchor is a trailing HTML
    comment, and a diagram treats that as a node rather than a comment, so writing one would
    corrupt the drawing. A diagram destination that stays plain forever is a normal state.
  - **No new dependency.** The destination grammar was measured over 2,165 real directives and
    reduces to three single-line shapes, so it is recognised by a pure textual function; the
    fenced-region computation is reused rather than reimplemented.

## [0.24.0] — 2026-08-17

> ### ⚠️ Two consumer-visible changes; both informational, neither moves the exit code
>
> **1. A dry-run's `+uuid X` no longer shows a value you can copy.** For a target that had no
> `uuid` yet, the value `plan_robustify` used to print was a fresh, random draft — different on
> every run, discarded unless `--write` actually followed. It now reads
> `+uuid <will be generated on write>` for a freshly-minted uuid; a **reused** uuid (already in the
> target's frontmatter) is unaffected, shown as before. `--write` itself is untouched — the file and
> the link still get the real, correct, matching uuid.
>
> **2. `check --json`'s output is now produced from a single tree read, not two.** The verdict is
> **byte-for-byte identical** to `v0.23.0` — verified, not assumed, on a real ~3500-file tree — only
> faster (measured **~2.1×** on that tree). Nothing to change in a consumer unless it depended on
> wall-clock timing.

## Fixed

- **An anchor comment no longer separates a link from its pandoc attribute block** (#65).
  `![](B.md){width="1.1in"}`, anchored by `--write`, used to become
  `![](B.md) <!-- uuid: … -->{width="1.1in"}` — the comment landing between the link and the block
  pandoc requires immediately after `)`. The block still rendered, just silently ignored: the
  document didn't fail to build, it rendered wrong, and nothing in the finding or the exit code said
  so. Fixed at every site that reads or writes the link grammar (detection, both write paths), so an
  already-anchored link with attrs is round-tripped correctly by `repair` too, not just newly
  anchored by `robustify`.

  A follow-up hardening, found by adversarial review rather than filed separately: a `}` inside a
  **quoted** attribute value (`{data-x="a}b"}`) was treated as the block's own closing brace and cut
  the match short — on `--write` that spliced the anchor comment into the middle of the attribute
  text itself, corrupting content #65's own fix never touched. Fixed alongside a second, independent
  copy of the same pattern that had drifted unhardened, which was silently making `repair` report
  **zero findings** for an already-anchored link whose target had genuinely moved.

- **A trailing space in a link's destination no longer turns a file link into an unhealable
  CONFLICT** (#67). `names_md("old/B.md ")` returned `False` — the space defeated `.endswith(".md")`
  — so `repair` misclassified an ordinary file link as a *directory* link, whose uuid then "lives in
  a non-README file": a false diagnosis, reported as `CONFLICT`. Unlike a real conflict, `--write`
  could never heal it either — permanently red over a link that was never actually broken. Fixed at
  the one shared primitive all three affected call sites go through; `resolve_href` stays untouched
  on purpose (the general whitespace-stripping question is `#74`'s, not this one's), so the fix's
  side effect is that the stray space gets cleaned up as part of the ordinary repair-a-stale-link
  path, not just stop being misdiagnosed.

- **A freshly-minted dry-run uuid is no longer printed as if it were final** (#41). See the note
  above. Also covers the `--create-readme` path, which mints its own uuid through a separate
  pre-pass and printed the same kind of throwaway value for both the directory link's finding and
  the `CREATE_README` finding itself — found by adversarial review as a second path to the same
  symptom.

- **`check` runs both its axes (integrity + strict) off ONE tree read instead of two** (#87).
  `build_index` and `plan_robustify` each used to walk and read every `.md` file independently, back
  to back, for the same invocation. `plan_repairs`/`plan_robustify` gain an **optional** `prescanned`
  parameter (`None` by default — every other caller, and every external consumer, sees zero change);
  `check` is the only caller that shares one scan between both. Measured on a large repo in the
  fleet: **29.4s → 13.8s** (this repository's own CI, on a smaller/differently-cached tree, measured
  **24.8s → 19.8s** in the adversarial review round — the mechanism is the same, the magnitude is
  machine-dependent). `--json` output verified byte-for-byte identical before and after, on the same
  tree, both times.

## Security / hardening

- **`write_text_keep_newlines` now refuses a symlink path, as a live assertion.** Verified first,
  not assumed: every path reaching this function already comes from `iter_markdown_files` (directly,
  or via an href resolved against a file that did), which yields `Path.resolve(strict=True)` —
  dereferencing every symlink component — so `path.is_symlink()` is unreachably `False` today,
  proven by driving the real `AGENTS.md → CLAUDE.md` layout end to end with a spy on the write call.
  A literal check-and-branch would have been dead code; the assertion gives the same protection for
  a **future** caller that bypasses that resolution, converting "silently writes through an alias"
  into "crashes immediately, at the one choke point every write goes through."

## Known issues (filed, not fixed here)

- **A hardlink to an indexed `.md` is indexed twice** — same symptom as `#85` (`uuid` reported in
  multiple files), different mechanism: `Path.resolve()` dereferences symlinks but does not collapse
  hardlinks (two directory entries, same inode). Verified live with `os.link()`, not speculative.
  Fixing it needs an inode-based identity check (`st_dev`/`st_ino` on POSIX), which is why it's its
  own issue rather than riding along on `#85`'s or this release's fixes. **#91**.

## [0.23.0] — 2026-08-16

> ### ⚠️ Two things change for a consumer, and neither is a regression
>
> **1. The file count can go DOWN, and that is the fix.** A symlink to a `.md` inside the scanned
> root used to be walked as a second document. Measured on a real repo the day this shipped:
> **3534 → 3533** files, one symlink that had been indexed twice. Nothing was lost; a duplicate
> stopped being counted.
>
> **2. A new category appears in the output**, text and JSON alike: `[out-of-root-link]` /
> `out_of_root_links`. It is **informational and does not move the exit code**. Anyone parsing the
> CLI output line by line should expect it.
>
> ### ⚠️ And two entries below were listed under `v0.22.0` but ship HERE
>
> The BOM fix (#68) and the balanced-parentheses fix (#71) were merged the same day as the release,
> **hours after the tag**. `git tag --contains` on both commits returns nothing, so a repo pinned at
> `v0.22.0` never received them despite the notes promising them. They are moved into this release,
> which is where they actually ship. Nothing needs to be done beyond moving the pin.

### Fixed
- **A symlink is another NAME for a file, not another file** (#85). `iter_markdown_files` yielded
  every walked path as-is, so a symlink to a `.md` **inside** the scanned root was read as a
  separate document. Sharing one instruction file across agents — `AGENTS.md`,
  `.github/copilot-instructions.md` and `CLAUDE.md` pointing at a single source, which is standard
  practice — therefore made the same `uuid` appear at three paths, and the integrity check failed
  with *"uuid in multiple files"*. Measured on a real repo on 2026-08-16, where it turned the gate
  red and **blocked every push** until the links were reverted.

  Files are deduplicated by resolved path now, and the **canonical** path is the one yielded. That
  second half is not cosmetic: relative links in a body resolve against the directory of the file
  they were read from, so reporting `.github/copilot-instructions.md` made a body link to
  `inventory/notes/` look broken and `repair` wanted to rewrite it. Otherwise walk order — which is
  directory order, so `aaa.md` can precede `zzz.md` — would decide which name wins.

  A symlink pointing **outside** the root is skipped, because the scan is defined by the root it was
  given. But it is **reported**, not silenced: such a file used to be indexed (reading a symlink
  follows it transparently), so its `uuid` resolved; skipping it quietly would turn a working robust
  link into `unresolvable` with nothing naming the cause — the exact failure this project exists to
  remove. A **broken** symlink is skipped without a word: reporting a dangling target is the dangling
  axis's job, not the indexer's.

  The report is informational and deliberately does **not** move the exit code: the *consequence*
  already fails on its own (a robust link to a uuid that stopped resolving is `unresolvable`, exit
  2). What was missing was the *cause*. A skipped link with no inbound references harms nothing, so
  failing on it would redden trees that are fine.

- **`--write` no longer deletes a file's UTF-8 BOM** (#68). The read side uses `utf-8-sig`, which
  consumes the mark so it cannot sit before the `---`; writing the resulting string back as plain
  utf-8 removed it from the file, on **all five write paths**, including `web-check --online --write` — a call site in another module that none of the original fixtures reached. This module's contract is byte
  preservation — it keeps CRLF meticulously — so dropping the BOM contradicted it.

  Worth recording *why it survived*: the CI Windows matrix exists for *"Windows-authored files
  (BOM, CRLF, path separators)"* and could not see this, because every BOM fixture put the mark on
  a file that gets **read**, never on one that gets **rewritten**. Coverage on the wrong side of an
  operation still reads as coverage.

- **Balanced parentheses in a link destination are no longer truncated** (#71). CommonMark allows
  them; `[^)]+` stopped at the first, so `[r](Log%20Analysis%20(February).docx)` was cut short and
  reported dead while the file was on disk. The report **concealed the cut** — its own
  `(resolves to …)` wrapper supplied the missing parenthesis, so the truncated path read as
  complete, and a reader who checked found the file present and concluded the *gate* was broken.

  Measured across the fleet, adjudicated against the reference CommonMark implementation: of 413
  hrefs containing a `(`, **266** are the real case (balanced, spaces already `%20`-encoded), 141
  carry raw spaces and are **not links at all** in CommonMark, 6 are unbalanced. Gate-scope
  differential: **1867 → 1862** dangling — five false reds removed, **zero findings gained**.

  ⚠️ **Two guards, both of which exist because the first version of this fix produced a false
  green.** The destination class is `[^()\s]`, not `[^()]`: a destination outside `<…>` cannot
  contain whitespace, and without that exclusion an *unmatched* `(` let the pattern run past the
  link's own `)` — across lines — absorbing a following healthy link, which then ceased to exist
  for the tool. And the pattern ends in `|[^)]+`, so a link nested past the bound degrades to the
  old truncating behaviour rather than ceasing to match. Both restore *visible and wrong* rather
  than *silent*.

  ⚠️ **Bounded at two levels of nesting**, which is 0 times exceeded in the fleet; arbitrary depth
  needs the scanner tracked in #74. And the swallow class is **narrowed, not closed**: a
  backslash-escaped `\(` or an angle-bracket destination still hands the pattern an unmatched
  opener. That cannot turn the gate green — the merged destination never resolves — but it collapses
  N findings into 1 with a mangled name. 0 instances in the fleet.

- **The shipped CI examples carried their own copy of the pin, and both had rotted.** Measured
  against the tags on the day this changed: the GitHub Actions example was pinned at `v0.20.4` with
  **3** releases published since, the Jenkins one at `v0.7.0` with **23** — and `v0.7.0` is 23 days
  old, in a project that is 34 days old. The drift is measured in releases, not in time: this moves
  fast enough that a pin can be twenty-three releases stale and less than a month old.
  They are the copy-paste templates for the very consumption path a release exists to serve, so a new
  adopter silently installed a gate far behind the one being documented. The canonical
  `recipes/README.md` was worse: its `curl` block *told you* to pin `v0.7.0`.

  Both examples now **derive** the version from the `ref` in `darnlink-gate.json`, reading the **key**
  with the JSON parser the recipe already depends on — not grepping the file, where a version string
  anywhere else (an excluded path, say) would win silently, which is the same "quietly picks a
  version" failure the step exists to prevent, one layer up. Any ref shape the recipe accepts works:
  tag, branch or SHA. The one it does not cover is a `ref` with no `@version` at all, and it says so.

  *Nothing fails when two copies of a version number drift* — which is why the second copy is gone
  rather than synchronised.

- **`__version__` said `0.5.0` against `0.22.0` in `pyproject.toml`** — seventeen minors adrift.
  Nothing reads it, which is the shape of a mine rather than a bug: harmless until someone adds
  `--version` or trusts `darnlink.__version__`, at which point the tool lies about itself. Derived
  from the installed package metadata now, and **lazily** (PEP 562): importing it eagerly cost
  **+34 %** on `import darnlink.cli` — `importlib.metadata` drags in the whole `email` stack — and
  darnlink runs as a pre-commit hook on every commit. The percentage is what reproduces: two
  independent runs of the same A/B agreed on ~34 % and disagreed on the absolute (+33 ms vs +45 ms),
  so the milliseconds belong to the machine and are not quoted as a property of the change.

### Added
- **A plain link written as an absolute filesystem path (`/home/user/x.md`) is now a named finding
  (`absolute_local_path`), instead of receiving no check at all.** `is_local_relative` excludes
  anything starting with `/`, so such a link was invisible to every existing axis: not `dangling`
  (that one shares the exclusion), not `out_of_scope` (that one names a real location outside
  `--root`; an absolute path names none). Unlike a relative link — which resolves to "this repo" on
  any clone — an absolute path can only ever resolve on the one machine that wrote it, and silently,
  since it was never reported either. Same treatment as `dangling` (FR-049): report-only, its own
  axis in `check --json`, and deliberately absent from the exit code, so no consumer's gate goes red
  on the day it upgrades.

- **`tests/test_recipe_examples.py` — the examples are code, and nothing had ever run them.** The
  release that added a `ps1-syntax` job on exactly that argument then put non-trivial shell into two
  example files with no gate at all. The tests **extract** the commands from the example files and
  execute them: against tag, branch, SHA and `@`-in-the-host refs, against a decoy version elsewhere
  in the JSON, and against the four cases that must fail loudly. Extracted rather than copied, so the
  examples cannot drift while the test passes against its own private copy.

- **A rung for feature 016 in `docs/elevating-your-link-gate.md`.** The ladder that tells a consumer
  how to climb never mentioned the rule, two releases after it shipped. §9 covers the keys, the
  exemption marker, and the traps that only show up when measured — including that **the pin and the
  keys must move in the same commit**, because an older CLI turns the whole axis into a green no-op,
  and that a **bare URL is invisible to the web axis** (only Markdown-syntax links are seen).

- **`AGENTS.md` and `.github/copilot-instructions.md`, as symlinks to `CLAUDE.md`** (#84). Copilot
  and anything following the `AGENTS.md` convention now read the same conventions as Claude, with no
  copy that can drift. Git stores symlinks natively (mode `120000`), so they travel on clone. This
  is the layout that exposed the indexing bug fixed above — adopting it here is what found it.

### Changed
- **`darnlang` pinned `v0.4.0` → `v0.9.1`** (#78, #80, #81, #82), which widens what the language
  gate judges in *this* repo's CI. It does not change darnlink's behaviour for a consumer; it is
  recorded because the pin moves and the baseline was reseeded. Three things worth carrying:
  - `v0.9.0` adds `.yml .yaml .toml .cfg .ini .sh .bash .groovy .gradle` plus the extensionless CI
    files by name (`Jenkinsfile`, `Dockerfile`, …). Being code, only their **comments** are judged: a
    YAML *value* is data, and firing on data is how a gate gets switched off.
  - `v0.9.1` adds `scanned_names` to the baseline. Until then the record held extensions only, so
    the extensionless files had no representation at all — if that branch of the scan ever narrowed,
    the count would **fall** and the ratchet would congratulate the repo for losing coverage.
  - The first reseed attempt ran against a **stale `darnlang` on `PATH`** and silently recorded ten
    extensions instead of nineteen. Caught by reading the baseline back, which is why the number is
    stated rather than trusted.

## [0.22.0] — 2026-08-13

> ### ⚠️ Moving your pin to this release CAN turn a green gate red — without you changing anything
>
> Not because of the new keys: those are opt-in, and a repo that sets none of them behaves exactly as
> it did on v0.21.0. It is the **dangling** fix below. Links with empty text — `![](photo.jpg)`, the
> shape pandoc emits for every image in a converted document — were not being filtered out, they were
> never *candidates*, so a tree full of broken embeds reported `dangling: 0`. Making them visible can
> only push the count up.
>
> **How likely is it to be you?** Measured across a nine-repository fleet, each with its own config,
> same command, only the version changing. Seven of them run `dangling: "repo"` with no ceiling — the
> setting that turns a finding into a closed push wall — and **two go red: 0 → 7 and 0 → 1. The other
> five stay at 0 and notice nothing.** An eighth, already at `warn`, moves 1704 → 1716; the ninth has
> the axis off.
>
> So: a minority, but not a rarity. Every single finding across the whole fleet was the same shape —
> `media/imageN.{jpeg,png,emf}` or a `foto-*.jpg` inside a CV or attachment converted by pandoc — so
> what it tracks is how many converted documents a tree carries.
>
> **Before you upgrade:** run the axis at `dangling: "warn"` to see your own number, then fix the
> links or raise the ceiling. This is a fix uncovering debt you already had, not a new failure — but
> it arrives as a red build either way, and being told afterwards is not being told.

### Added
- **`darnlink-gate`: the `own_web` keys, so feature 016 can actually be switched on.** The rule
  shipped in v0.21.0 lives in the CLI; until now no gate invoked it, so it protected nothing. Both
  recipes — bash and PowerShell — now read `own_web` (a list of owners), `own_web_from_origin` (bool)
  and `own_web_max` (int) and pass them through — including an explicit `own_web_max: 0`, which the
  PowerShell config reader dropped at first because it tests truthiness and PowerShell reads JSON `0`
  as false. That is the one value whose distinction from *absent* is the whole point of the budget.

  Three details keep it honest, and each is the same rule an existing key already follows:

  - **`own_web_from_origin` is its own key, not a sentinel inside the list** — an owner literally
    called `origin` has to stay expressible, the same reason the CLI has a flag rather than
    `--own auto`.
  - **A non-numeric budget counts as ABSENT, never as infinite.** Silently widening an allowance is
    the one direction a config typo must not be able to go (`dangling_max` established this).
  - **An exit 1 is treated as likely-config, but only when this run passed an `own_*` flag.** Feature
    016 makes exit 1 reachable from configuration — a budget with no owners, an unresolvable origin —
    and reporting that as a red gate would send someone hunting for broken links that do not exist.
    But exit 1 is *not* exclusively a usage error: `uvx` exits 1 on its own failures and an uncaught
    exception exits 1 too, so an unconditional reading would have turned those green for every
    consumer with `web: true`, including repositories that never adopted 016 — a worse guarantee than
    before the key existed. And it respects `fail_closed`: under fail-open the axis is dropped with a
    warning, in CI it becomes 4, because there the gate *is* the wall and an axis that could not run
    is not a pass. It is not routed to `bail()` either: that exits the script and would skip every
    axis after this one, the bug this same pass was fixed for once already.

  The wiring is asserted on the **invocation**, not the verdict: without a token an unreadable
  destination is `web_unverifiable` and the gate exits 0 whether or not the flags were passed, so a
  verdict-based test cannot tell — and did not. Dropping the `--own` loop entirely left every other
  recipe test green until the shim started recording argv.

  Two further silent no-ops closed while wiring it, both found by mutation rather than by reading:

  - **An empty owner entry passed without a word.** `[""]` flattens to exactly what an absent key
    gives, so the list length is now read separately from its value — and a *partially* empty list is
    named too, the case where the config lists three owners and the gate enforces one.
  - **`web-check`'s exit 4 had no test protecting it from the `rc>3` fail-open heuristic.** Its codes
    are all in 0..4 and none of them means *unreachable*, which is why the web verdict is marked
    final; remove that immunity and a genuine 4 — exactly how feature 016 reports an owned
    destination with no uuid — turns into **0** under the default, with the suite green.

### Fixed
> ⚠️ **Two entries that used to live here ship in [0.23.0], not in this tag.** The BOM fix (#68) and
> the balanced-parentheses fix (#71) were merged hours *after* `v0.22.0` was cut —
> `git tag --contains` on either commit returns nothing. They were listed here by mistake, so a repo
> pinned at `v0.22.0` believed it had two fixes it did not have. Moved to the release that actually
> carries them; recorded rather than silently deleted, because anyone who read these notes acted on
> them.

- **Nothing had ever parsed `recipes/darnlink-gate.ps1`.** The recipe tests skip on Windows and no CI
  job ran `pwsh`, so a syntax error in the shipped PowerShell recipe would have reached consumers as
  a script that does not start. CI now parses it. Parsing is not testing — it never runs the gate —
  but it is the one failure mode a bash-only fleet cannot see at all.

- **A link with empty text — `![](photo.jpg)`, what pandoc emits for every image in a converted
  `.docx`/`.odt` — was invisible to every axis, not merely unreported.** `MD_LINK_RE` required at
  least one character of link text (`[^\]]+`), so such a link never matched: it was not a finding
  that got filtered, it was never a candidate. The axis then printed `dangling: 0` over a tree full
  of broken image embeds, which reads as *"no broken links"* but only ever meant *"none of the
  shapes the regex recognises"*.

  Measured on one repository running the wall at maximum, in its own gate scope: **127 links with
  empty text, 7 of them pointing at a target that does not exist**, and the axis printed
  `dangling: 0`. Since those files are converted documents, they arrive in blocks and nobody
  re-reads them.

  ⚠️ **Adopting this is not a no-op for a consumer.** `MD_LINK_RE` has three call sites, so
  the same repository also gains **36 newly visible web links** (none a `/blob/` URL today, so its
  web gate does not flip — the shape of those URLs, not a guarantee), and `--create-readme` gains a
  path where `![](media/)` can create a `README.md`. A repo at `dangling: repo` with `dangling_max`
  unset goes **0 → 7 and its push wall closes**: fix the links or raise the ceiling *before* moving
  the pin, not after.

  Reported as the pandoc attribute suffix (`{width="1.1in"}`) hiding the link; it was not.
  The pattern stops at the `)` and never looks past it, so `![alt](x.jpg){width="1.1in"}` was always
  seen. The two shapes simply co-occur. Both are pinned in tests so the real cause — the empty text —
  cannot be re-diagnosed from the same coincidence. `ROBUST_LINK_RE` widens alongside `MD_LINK_RE`,
  so an anchored empty-text link cannot be plain to one function and robust to another — a coupling
  that matters to the **repair** axis and has its own tests, since reverting that half alone leaves
  every `dangling` test green. FR-051.

### Known issues — read this before moving a pin

None is introduced by this release, but they belong where a consumer deciding on an upgrade will
see them rather than buried under *Fixed*. **One of them is live**; the rest are latent at 0
occurrences across thirteen repositories.

- ⚠️ **LIVE — balanced parentheses in a destination are truncated at the first `)`** (#71).
  CommonMark allows them; `MD_LINK_RE` does not, so the link is cut short and reported dead while
  the file it names sits on disk, clustered in mirrored attachment filenames (`(Parte 1)`,
  `(February - Monthly)`). The report conceals itself: its own `(resolves to …)` supplies the
  missing parenthesis, so the truncated path reads as complete, and a reader who checks finds the
  file present and concludes the *gate* is broken.

  **Size it by 20, not by 104.** Two measurements of the same repository, and only the first is what
  a wall would enforce:

  | measurement | count |
  |---|---:|
  | `dangling` findings the gate **emits** that are truncations | **20** |
  | truncated links **in the tree** whose paren-completed target exists | 104 |

  An earlier version of this entry printed only the 104 and said raising `dangling` to `repo` "would
  close the wall on 104 files that exist". That is wrong: a wall counts what the axis emits, and
  most of the 104 never reach it. The gap between the two is filters this note does not fully
  account for, which is exactly why the actionable number is the one measured at the gate.

  Pre-existing and orthogonal to this release.

- **`--write` detaches a pandoc attribute block** (#65). The anchor lands between the link and its
  `{…}`, so the block stops applying. Pre-existing: a non-empty link text has always done it. The
  tests added here pin that the block is never *deleted*, which is the worse neighbour of the two.
- **`--write` silently drops a file's UTF-8 BOM** (#68) on all four write paths. CRLF is preserved
  meticulously; the BOM is not, and three places in this repo imply otherwise — including the CI
  Windows matrix, whose stated purpose is BOM/CRLF and whose BOM fixture only covers the *read*
  path, so it cannot see this.
- **A trailing space in a destination makes `repair` emit a CONFLICT it cannot heal** (#67):
  a trailing space makes `names_md` false, the link is classified as a directory link and becomes a
  `CONFLICT` diagnosed as *"path and uuid disagree"* — which is untrue, and `--write` never heals
  it, so the gate stays red.

## [0.21.0] — 2026-08-13

### Added
- **`web-check --online` can fail on a destination *you own* that has no `uuid`** — feature 016,
  opt-in (`specs/016-own-repo-web-strictness/spec.md`). The web axis is forgiving by design: a
  destination that fetches 200 without a `uuid` is `web_unverifiable` and the run still exits 0,
  because the file lives in someone else's repository and cannot be fixed from here. When it is
  **yours** that is not an external limitation — it is a missing two-line edit in a repo you control,
  and nothing ever said so.

  - **`--own OWNER`** (repeatable, stripped and case-folded) names the owners you control.
    **`--own-from-origin`** adds this repo's `origin` owner — a separate flag rather than a magic
    `--own auto`, so an owner literally called `auto` stays expressible. If it cannot resolve, the run
    is a **usage error**, even when explicit owners were given: it is a request, not a fallback.
  - **`web_own_no_uuid`** at exit **4**, not 3 — 3 promises "re-run with `--write`", and darnlink
    cannot fix this one. The message names owner, repo and path, and never suggests `--write`.
  - **`--own-max N`** budgets it so a repo can adopt the rule before reaching zero. The budget
    silences the *verdict*, never the *finding*, and never shields another exit-4 cause. The report
    says where the count stands in all four cases — including **over** the budget, because a budget
    that goes silent exactly when it is exceeded is the one moment its number is worth reading.
  - **`<!-- darnlink-own-exempt -->`** exempts a link whose destination is machine-regenerated, where
    a `uuid` is futile — from the new finding, from anchoring, and from `web_mismatch`, since a
    regenerating destination is precisely one whose uuid drifts. Honoured **with or without an owner
    set**: it states a property of the link, not of the run.

  Two exclusions, textual and offline: a destination that is not `.md` can never carry frontmatter,
  and one pinned to a **commit SHA** can never be given one retroactively. Tags are deliberately not
  excluded — a tag is textually indistinguishable from a branch of the same name.

  With no owner set, behaviour is unchanged byte for byte in the **text report, the exit code and the
  files on disk**, with two named departures: the exemption marker, and three keys that
  `--json` gains unconditionally — the two new counters at zero, and `own_max` — so a consumer can
  tell both that the axis ran and what budget it ran under.

## [0.20.5] — 2026-08-13

### Fixed
- **A tokenless `403` is the anonymous rate limit, not a private repo — and the web axis now says so
  instead of printing a quiet `clean`.** `web-check` reported *"cannot read destination: private repo
  and no token provided"* for any `403` without a token. That was wrong every time: GitHub answers
  **404**, not 403, for a private repo you cannot see — as `_classify` already explained thirteen
  lines below the message. A tokenless 403 is the **60/h-per-public-IP anonymous quota**, shared by
  every machine behind the same NAT, so the message sent readers hunting for a permissions problem
  they did not have, on destinations that were public and returned 200 in a browser.

  **This is not only a mislabel: it can be a false green.** An un-anchored web link is only
  discoverable if the destination can be **read**. Measured on one tree, minutes apart: *without*
  token `exit 0`, *with* token `exit 3` — the link needed anchoring and the tokenless run could not
  tell. So `ok 0 | unverifiable N` means *"could not look"*, not *"nothing to verify"*, and it is
  indistinguishable from a repo with no cross-repo links at all.

  Three surfaces changed accordingly: the finding text now names the quota and the remedy; the
  summary line no longer says plain `clean` when anything was unverifiable; and both recipes (bash
  and PowerShell) warn when the axis runs without a token. The docs that promised *"public repos work
  tokenless"* and *"never a false green"* are corrected — **give the axis a token even for public
  destinations**: private ones need it for permission, public ones for quota.

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
- **`web-check --online` no longer dies on an href it cannot send.** Two routes took the whole run
  down, and each escaped `_fetch_once`'s `except (URLError, TimeoutError, OSError)` by a different
  door: **whitespace or control characters in the href** — mirrored third-party content carries two
  truncated URLs with a space between them, and `http.client.InvalidURL` descends from
  `HTTPException`, not `OSError` — and **a non-ASCII path**, where `http.client` encodes the request
  line as ASCII and raises `UnicodeEncodeError`, a `ValueError`. An accented filename was enough.

  Every URL field is now percent-encoded (`safe="/%"` on the path, so an href already written with
  `%20` is left alone), and an href carrying a character the client would refuse is reported
  `web_unverifiable` instead of being sent.

  **The conservative half is the point.** The tempting alternative — forbid those characters only
  *inside* the parsed groups, so more links can still be resolved — truncates the path at the first
  offending character, fetches a *different* file, and reports its 404 as a real break. A false
  `web_not_found` in a blocking gate is worse than the crash it replaces. Recovering the links this
  rejects is deliberately left to a separate change.

  **The one true regression, stated plainly:** an href whose offending character sits at or after the
  first `#` or `?` — `…/a.md#a b`, `…/a.md#s "Title"`, `…/a.md?plain=1 "Title"` — used to verify,
  because the path group stops there and the URL that went on the wire was clean. It is now
  `web_unverifiable`. Everything else this rejects **crashed** before, so it is not a regression.
  And `web_unverifiable` cannot fail a gate, so the change can turn a green run into a quieter one,
  never into a red one.

  Client-side URL errors get their own sentinel, kept out of the retry set: retrying a deterministic
  rejection spends real sleeps and can never succeed, and folding it into the network sentinel would
  bury darnlink's own defect under "network error". Strictly, 013 forbade neither crash — FR-008
  covers an *unrecognised* URL shape (this one the regex accepts) and FR-009 is worded for *transport*
  errors — so they fell through the gap between two requirements each written assuming the other
  covered it.

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

[Unreleased]: https://github.com/txemi/darnlink/compare/v0.24.0...HEAD
[0.24.0]: https://github.com/txemi/darnlink/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/txemi/darnlink/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/txemi/darnlink/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/txemi/darnlink/compare/v0.20.5...v0.21.0
[0.20.5]: https://github.com/txemi/darnlink/compare/v0.20.4...v0.20.5
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
