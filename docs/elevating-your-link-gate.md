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

> **Using the [`darnlink-gate`](../recipes/README.md) recipe?** This flip is **one line** — set
> `"mode": "max"` in `darnlink-gate.json`; the hooks and CI don't change. `mode=max` runs exactly the
> command above (dry-run) at the whole-repo wall, and stays at strict in the staged pre-commit by
> design (§7). Copy-paste hook/CI files: [`recipes/examples/`](../recipes/examples/).

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
[`recipes/examples/`](../recipes/examples/) — [`pre-commit`](../recipes/examples/pre-commit) (staged) ·
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
- **Honest about what it can't reach.** A **private** destination needs a `GITHUB_TOKEN`/`GH_TOKEN`
  (public repos work tokenless); without one it reports `web_unverifiable` and does **not** fail the
  build — never a false green, never a crash. Run the online layer wherever a token already lives (a
  self-hosted CI runner with a GitHub App is the natural home).
- **Narrow by design.** It *anchors* a plain link and *verifies* an anchored one; it does **not** hunt
  for where a moved target went (no web-side index to walk deterministically) — that's left to the
  human/LLM layer, which re-anchors once it knows the new URL.

Add it as one extra step in the wall (pre-push + CI), gated on having a token for any private targets.

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
      `web-check --online` to the pre-push/CI wall, and provide a token for any private destinations.
