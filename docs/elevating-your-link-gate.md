---
uuid: e95eaed1-9866-4c48-a0d7-99a6382f5bf9
---
# Elevating your link gate — from "robust links don't break" to fail-closed

A playbook for taking an existing repository all the way to the strictest darnlink gate:
**every link points at a file that carries a `uuid`.** Once you're there, no refactor — moving a
file, renaming a folder, reorganizing a whole subtree — can silently break a link, because darnlink
can always re-anchor by `uuid`.

The [README quality-gate section](../README.md#never-break-a-link-again--add-it-to-your-quality-gate)
explains the *what* (the flags, the hooks, the CI wiring). This is the *how*: the end-to-end campaign
to elevate a real repo, the strategy that keeps it tractable, and the traps to avoid. It's written
generically — the running example is "a repo that keeps a local **mirror** of an external system
(an issue tracker, a wiki, a chat, a document store) plus hand-authored notes that link into it."

## 0. The three levels of strict

darnlink's gate has three settings, each stricter than the last:

| Command | Fails when… | This is the baseline for… |
|---|---|---|
| `darnlink .` | a **robust** link (already `uuid`-anchored) points at a moved/missing target | "don't break what's robust" |
| `darnlink . --robustify` | a **plain** link points at a target that **already has** a `uuid` (un-anchored) | "anchor everything anchorable" |
| `darnlink . --robustify --create-frontmatter` | a **plain** link points at a target **without** a `uuid` (it *could* get one) | **the maximum — this playbook** |

The maximum is a simple, memorable rule:

> **A link to a file that has no `uuid` frontmatter fails the gate. A file with no `uuid` that
> nobody links to is fine** — `--create-frontmatter` only ever looks at *links*, never at orphan
> files.

That second half is what makes the maximum reachable: you don't have to `uuid` the entire repo, only
the files something actually links to.

## 1. Read the gap

Point the strictest check at the repo and list what it flags:

```bash
# Everything a fail-closed --create-frontmatter gate would flag today (dry-run — writes nothing):
darnlink . --robustify --create-frontmatter --exclude clones 2>&1 | grep '\[robustify\]'
```

Each line is `[robustify] <source-file>: <target> +uuid <hash>` — "this link could be robustified;
its target would get that `uuid`." Group them to plan the work:

- **by target** — which files need a `uuid` (the ones being linked *to*).
- **by source tree** — who holds the plain links (your own docs vs. the mirror's internal
  cross-links).

Two exclusions matter from the start: **always `--exclude` any nested git clones** (never write into
a foreign repo you vendored), and typically `--exclude` any `archive` tree you don't intend to touch. Excluding your *mirror* while you scope the "your content" number is useful too — see §3.

> Since 0.8.0 the gap also includes **directory links** — a plain link to a *folder* that has a
> `README.md`. They robustify and heal exactly like file links, but they pin the gate to a minimum
> version; see the note in §6 before you close them.

## 2. Two buckets

Every flagged link falls into one of two buckets, and only one is safe to do immediately:

- **Bucket A — target is hand-authored** (a note, a README, a doc you wrote). Safe to robustify
  **now**: `--create-frontmatter` gives it a `uuid` and nothing will ever overwrite it.
- **Bucket B — target is *generated*** (a rendered view a script rewrites: an index, an export, a
  report). **Do not** just add a `uuid` to the file — the next time the generator runs it rewrites
  the file and **wipes the `uuid`**, and your gate goes red again. Bucket B needs the *generator* to
  cooperate first (§4).

Classifying is the crux. For each flagged target, ask: *does a script write this file?* Basenames are
a good heuristic (a generated `INDEX.md`, `_index.md`, `report.md`, `<key>.md` from an exporter) but
verify against what your generators actually emit. Build a **guard list** of generated basenames; you
feed it to `--no-create-frontmatter-for` so the mass robustify never touches Bucket B.

## 3. Robustify Bucket A (the mass, safe pass)

```bash
darnlink . --robustify --create-frontmatter --write \
  --exclude clones --exclude mirrors --exclude archive \
  --no-create-frontmatter-for INDEX.md --no-create-frontmatter-for _index.md \
  --no-create-frontmatter-for report.md   # …one per generated basename
```

This anchors every plain link whose target is hand-authored, creating a `uuid` on those targets.
Excluding the mirror here keeps the number to *your* content; the mirror is Bucket B and comes later.

**Verify before you commit — this is the safety net, not the guard:**

1. **No generated file got a `uuid`.** Diff the result; cross-check every newly-frontmattered file
   against your generated-basename list. If one slipped through the guard, revert it.
2. **Each generator's own `--check` (if it has one) is still green.**
3. **The gate is green.** If it reports `[unresolvable]` — a robust link whose `uuid` "not found" —
   you have a *dangling anchor*: a link was anchored to a target you then reverted. Strip the
   ` <!-- uuid: … -->` off that link (leave it plain; it's Bucket B).

### Traps that will bite you here

- **The `while read` trap.** If you build the `--no-create-frontmatter-for` list from a file with a
  shell `while read`, a missing trailing newline silently drops the **last** entry — and that one
  generated basename gets frontmatter. Caught only by verification step 1.
- **A raw robustify does not respect an external allowlist.** If you keep a separate
  "generated files" allowlist for your gate wrapper, `darnlink . --robustify --write` **ignores it**
  and will rewrite links *inside* those generated files too (futile — regeneration wipes them). Use
  `--no-create-frontmatter-for` / `--exclude`, and revert any generated file the pass touched.

## 4. Make generators cooperate (Bucket B)

A generated file is fine as a **linkable target** — you *want* things to link to a generated
`INDEX.md` — it just must not create endless gate-work. Two mechanisms, used together:

**(a) The ignore-links marker.** The generator emits, right below the frontmatter:

```
---
uuid: …
---
<!-- darnlink-ignore-links -->
```

darnlink then leaves the *outbound* links inside that file alone (they're rewritten plain on every
run — anchoring them is pointless), so the file's own links never fail the gate, no matter how strict.
See [FORMAT.md §5](../FORMAT.md#5-opting-a-file-out) <!-- uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef -->.

**(b) A stable, preserved `uuid` (provenance).** For the file to be a robust *target*, its `uuid`
must survive regeneration. Make the generator **preserve-or-create**: read the `uuid` from the
existing file if present, mint one only if absent, and re-emit it. Optionally stamp *who* generated
it, so provenance is legible on disk and greppable:

```
---
uuid: <stable; read from the existing file or minted once>
generator:
  path: tools/x/render.py          # repo-relative producer (for humans)
  uuid: <the generator's own constant id>   # survives renaming the script; grep it to list its output
---
<!-- darnlink-ignore-links -->
```

The `generator.uuid` is a module-level constant in the script. Two identities, two questions:
*"is this the same file?"* (the file `uuid`) vs *"who made it?"* (the generator `uuid`).

> **Determinism matters for byte-compare `--check` gates.** If a generator ships a `--check` that
> re-renders in memory and diffs against disk, preserving the `uuid` keeps it deterministic — the
> file exists, so its `uuid` is reproduced, so render == disk. **Never mint a fresh `uuid` on every
> render** or the check flaps red forever.

A ~40-line, stdlib-only helper does this; each repo/generator can carry its own copy (no shared
runtime dependency), inline it, or share one. The essence:

```python
import re, uuid as _uuid
from pathlib import Path
_UUID_RE = re.compile(r"^uuid:\s*([0-9a-fA-F-]{36})\s*$", re.M)

def provenance(path, gen_path, gen_uuid, *, ignore_links=False):
    p = Path(path); fu = None
    if p.exists() and p.read_text().startswith("---"):
        head = p.read_text().split("\n---", 1)[0]
        m = _UUID_RE.search(head); fu = m.group(1) if m else None
    fu = fu or str(_uuid.uuid4())
    block = f"---\nuuid: {fu}\ngenerator:\n  path: {gen_path}\n  uuid: {gen_uuid}\n---\n"
    return block + ("<!-- darnlink-ignore-links -->\n" if ignore_links else "")
```

Once a generator does this, its output can leave any external allowlist — the in-file marker is the
single source of truth. The allowlist shrinks to empty as you migrate generators, which is the goal:
no list to maintain.

## 5. Bulk-adopting an existing mirror

Your mirror already has thousands of generated `.md` files with no `uuid`. You don't need the live
system to fix them — **the raw source is usually stored next to the rendering** (the exporter keeps
`<key>.json` beside `<key>.md`, or the raw `.html`/`.eml`). So you can:

1. **Migrate the generator** (§4) so *future* refreshes preserve the `uuid`.
2. **Back-fill the existing files offline** — either re-render each `.md` from its stored raw with
   the now-provenance-aware generator, or just prepend the provenance block (matching what the
   generator now emits) if the body is unchanged. Either way the *raw* download (`.json`, `.html`)
   is never touched — you only give the *rendering you produced* an identity.

A mirror is a web of internal cross-links (issue→issue, page→page). Because every generated file
carries the **marker**, those internal links are ignored wholesale — they collapse out of the gap in
one move. What remains is only what *your* content links to.

> Mirror files are **stable-keyed** (`<KEY>.md` never moves) and rarely regenerated. So even before
> you migrate their generator, a back-filled `uuid` is durable in practice — and once migrated, a
> refresh preserves it. If a generator is genuinely one-shot and has no home you control (an ad-hoc
> ingest), back-filling + a note is a legitimate stopping point; flag it as the known-fragile spot.

## 6. Flip the gate

When the gap reads **0**, switch your gate command to the maximum:

```diff
- darnlink . --robustify            # or `darnlink check`
+ darnlink . --robustify --create-frontmatter
```

Re-verify 0, and you're fail-closed: from now on, a link to any file without a `uuid` fails.

> **Using the [`darnlink-gate`](../recipes/README.md) <!-- uuid: b4e6058b-4af0-4d23-a826-975a8fc78e6f --> recipe?** This flip is **one line** — set
> `"mode": "max"` in `darnlink-gate.json`; the hooks and CI don't change. `mode=max` runs exactly the
> command above (dry-run) at the whole-repo wall, and stays at strict in the staged pre-commit by
> design (§7). Copy-paste hook/CI files: [`recipes/examples/`](../recipes/examples/) <!-- uuid: f8da8344-8293-4c05-b154-8bdb088adddf -->.

> **⚠️ Directory links pin your gate to ≥ 0.8.0.** Since 0.8.0 a robust link can target a *folder*
> (anchored to its `README.md`'s uuid — [FORMAT.md §4.1](../FORMAT.md#41-directory-links) <!-- uuid: 9052d864-2a45-4ed4-8725-d8a394e7a7ef -->). Two consequences for the wall:
> **(1)** `--robustify` now flags plain **directory** links too, so they are part of the gap you close
> above; **(2)** the gate binary **itself** must be ≥ 0.8.0 — an older `darnlink` doesn't understand a
> directory link, so its `repair` pass treats a robust `[x](foo/) <!-- uuid -->` as *broken* and
> rewrites it to `foo/README.md` (the file), silently destroying the folder link. **Require
> `darnlink >= 0.8.0` in your gate before you robustify the first directory link** (pin it to a
> concrete `0.8.0`-or-newer release) — bumping an already-live gate from an older pin, and robustifying
> the directory links, is one atomic step. A folder with no
> `README.md` isn't anchorable until it has one; the opt-in `--create-readme` writes it (respecting
> `--exclude`/`--only`, and never creating the folder itself).

## 7. Lock it in — the wall architecture

A gate only guarantees anything at the layers where it actually runs and blocks. Use more than one,
each at the scope that fits — this is deliberate, not redundant:

| Layer | Scope | Why this scope |
|---|---|---|
| **pre-commit** | **staged only** | Fast; makes you responsible for what *you* commit. Whole-repo here **deadlocks** parallel contributors — a plain link someone else left in flight blocks *your* clean commit. Don't. |
| **pre-push** | **whole repo** | `git push` is deliberate and infrequent → no deadlock. This is the local wall that stops anything broken from leaving your machine — the guarantee, even if CI is down. |
| **CI** (hosted or **self-hosted**) | **whole repo** | The unbypassable server-side wall — catches even a `--no-verify` bypass. On a private repo where hosted CI minutes are billed or branch protection is unavailable, a **self-hosted runner** (e.g. a home CI box) is the natural home; it runs the same check with no billing. |

The pre-commit and pre-push checks both call the same fail-closed command; flipping to
`--create-frontmatter` in one place raises them together. The scope split (staged locally, whole-repo
in the wall) is the same recommendation the README makes for multi-contributor repos — here it's the
load-bearing reason the maximum is livable.

**Complete, copy-paste files for all three layers** are in
[`recipes/examples/`](../recipes/examples/) <!-- uuid: f8da8344-8293-4c05-b154-8bdb088adddf --> — [`pre-commit`](../recipes/examples/pre-commit) (staged) ·
[`pre-push`](../recipes/examples/pre-push) (whole repo) ·
[`github-actions-darnlink-gate.yml`](../recipes/examples/github-actions-darnlink-gate.yml) and
[`Jenkinsfile-stage.groovy`](../recipes/examples/Jenkinsfile-stage.groovy) (the server wall,
fail-closed). They're whole working artifacts, not snippets to assemble — assembling the CI one wrong
is how you get a wall that fails *open*.

## 8. Extend the wall to cross-repo web links (opt-in `web-check --online`)

Everything above hardens links **within one tree**. If your docs are split across repos — a file in
repo A links to a file in repo B by its `https://github.com/owner/B/blob/…` URL — the core gate can't
help: B's `uuid` lives in a repository the core never scans. Those cross-repo URLs 404 silently the
moment the target moves in B, and no amount of local strictness catches it.

`web-check` closes that last gap, and it's worth adding **once you actually have cross-repo links**:

```bash
# anchor plain cross-repo links to their destination's uuid (writes the <!-- web-uuid --> marker)
darnlink web-check . --online --write

# in the wall (pre-push / CI): verify every anchored web link still matches its destination; fail on drift
darnlink web-check . --online          # exit 4 on mismatch/404, 0 clean
```

Why it's safe to add to an existing fail-closed gate:

- **Opt-in and off by default.** Nothing happens without the `web-check` subcommand *and* `--online`.
  Your existing `darnlink`/`check` gate is completely unchanged — it never makes a network call.
- **It won't fight your core gate.** The anchor it writes is `<!-- web-uuid: X -->`, a *different*
  marker from the core's `<!-- uuid: X -->` — the core ignores it entirely, so a web anchor never
  trips the local `unresolvable` check. (This is the whole reason it uses its own marker.)
- **Honest about what it can't reach — but give it a token anyway, and here is why.** A `GITHUB_TOKEN`
  is needed for **both** kinds of destination: private ones for *permission*, **public ones for
  *quota*** (anonymous GitHub API calls are **60/h per public IP**, shared by every machine behind the
  same NAT). Without one it reports `web_unverifiable` and does **not** fail the build — never a
  crash.

  ⚠️ **But "does not fail the build" is not the same as "never a false green", which this page used
  to claim.** An un-anchored web link is only discoverable if the destination can be **read**.
  Measured on one tree, minutes apart: **without token `rc=0`** (green), **with token `rc=3`** — the
  link needed anchoring and the tokenless run could not tell. So an `ok 0 | unverifiable N` is *"could
  not look"*, not *"nothing to verify"*, and it is indistinguishable from a repo with no cross-repo
  links at all. Quote the token condition next to any web figure, or it is not comparable between two
  runs. Run the online layer wherever a token already lives (a self-hosted CI runner with a GitHub
  App is the natural home).
- **Narrow by design.** It *anchors* a plain link and *verifies* an anchored one; it does **not** hunt
  for where a moved target went (no web-side index to walk deterministically) — that's left to the
  human/LLM layer, which re-anchors once it knows the new URL.

Add it as one extra step in the wall (pre-push + CI), and give it a token — for **quota** on public
targets, for **permission** on private ones.

## 9. The last rung: stop letting your OWN repos off the hook (`own_web`)

Everything in §8 is forgiving on purpose. A destination that fetches 200 but has no `uuid` is
`web_unverifiable` and the run still exits 0, because the file lives in **someone else's**
repository: you cannot add frontmatter to a repo you do not control, and a gate that fails on
something you cannot fix is a gate people delete.

That reasoning stops applying the moment the destination is **yours**. Then it is not an external
limitation — it is a missing two-line edit in a repo you control, and until this rung existed nothing
ever said so. The link stayed un-anchorable forever, counted in the same bucket as a link into a
stranger's repository.

Your `darnlink-gate.json` needs `"web": true` and `"mode": "max"` already; then add the keys. It is
**one JSON object** — the block below shows the three keys together, not three separate files, and it
has no comments in it, because the recipe parses this file with a strict JSON reader and swallows the
error: a file it cannot parse gives you *every key at its default*, silently, including a `ref` far
older than yours.

```json
{
  "own_web_from_origin": true,
  "own_web": ["your-org", "your-user"],
  "own_web_max": 5
}
```

`own_web_from_origin` adds this repo's own GitHub owner; `own_web` names owners explicitly (the two
combine); `own_web_max` is a budget, so you can adopt before you are at zero.

A finding is `web_own_no_uuid`, and it names owner, repo and path so you know which file to open. It
never suggests `--write`: darnlink cannot fix this one from here — the edit belongs in the other
repository. It fails the gate at **exit 4** — *unless* a budget covers it, which is exactly what
`own_web_max` is for: under the budget the finding is still reported, only the verdict is silenced.

Three things worth knowing before turning it on:

- **The pin and the keys must move in the SAME commit.** A CLI older than v0.21.0 does not know the
  flags, so `web-check` exits 1 as a usage error, the recipe reads that as a config problem and drops
  the axis — with a warning on stderr, but a **green** exit under the default fail-open. Measured.
- **`<!-- darnlink-own-exempt -->`** next to a link exempts it — for a destination that is
  machine-generated, where adding frontmatter is not yours to decide. Never anchored, never stale.
- **Only Markdown-syntax links are seen.** A bare `https://…` URL pasted into a list is invisible to
  the entire web axis: not anchored, not verified, not even counted as unverifiable. Measured with
  both spellings of the same URL in the same file — one finding, not two. So a clean web number is a
  statement about your `[text](url)` links, and about nothing else.

**Expect a backlog on the first run, and budget for it.** Measured on a nine-repository fleet the day
this feature was specified: **17 confirmed** links to files we owned and had never given a `uuid`
(and up to 24 counting the unresolved). That is why `own_web_max` exists — it is a budget, not a
cliff. Once that debt is paid the number stays at or near zero and the rung changes job: on the same
fleet two days later, with the eight web-enabled repos cleaned up, switching the rule on found
**one**. Both numbers are real; which one you get depends entirely on whether you have paid yet.

## Checklist

- [ ] Read the gap with `--robustify --create-frontmatter`; split into Bucket A / Bucket B.
- [ ] Mass-robustify Bucket A with a complete `--no-create-frontmatter-for` guard; **verify** (no
      generated file got a `uuid`; gate green; no dangling anchors).
- [ ] For each generator: emit the `ignore-links` marker + a **preserved** `uuid` (+ optional
      `generator` provenance). Drop it from any external allowlist.
- [ ] Back-fill existing generated/mirror files offline from their stored raw; never touch the raw.
- [ ] Gap = 0 → flip the gate to `--create-frontmatter`.
- [ ] Wire the walls: pre-commit (staged) · pre-push (whole repo) · CI/self-hosted (whole repo).
- [ ] **If you have cross-repo web links:** anchor them with `web-check --online --write`, add
      `web-check --online` to the pre-push/CI wall, and provide a token (quota for public destinations,
      permission for private ones).
