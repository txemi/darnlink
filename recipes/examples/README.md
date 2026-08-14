---
uuid: f8da8344-8293-4c05-b154-8bdb088adddf
---

# darnlink-gate — complete, copy-paste examples

Runnable versions of the four pieces from [`../README.md`](../README.md#adopt-it-in-a-repo-the-wall-in-4-pieces) <!-- uuid: b4e6058b-4af0-4d23-a826-975a8fc78e6f -->.
Each file is a whole, working artifact — not a snippet to assemble — because assembling the CI one
wrong yields a wall that fails **open** (green build, nothing validated). They wire the same generic
recipe ([`../darnlink-gate`](../darnlink-gate)) at the scope that fits each layer.

| File | Layer | Scope | Fail mode |
|---|---|---|---|
| [`pre-commit`](pre-commit) | local, per-commit | **staged** (fast; no cross-session deadlock) | open |
| [`pre-push`](pre-push) | local wall | **whole repo** | open (flip to closed inside) |
| [`github-actions-darnlink-gate.yml`](github-actions-darnlink-gate.yml) | server wall | **whole repo** | **closed** |
| [`Jenkinsfile-stage.groovy`](Jenkinsfile-stage.groovy) | server wall (self-hosted) | **whole repo** | **closed** |

**The scope split is deliberate** (see [`../../docs/elevating-your-link-gate.md §7`](../../docs/elevating-your-link-gate.md) <!-- uuid: e95eaed1-9866-4c48-a0d7-99a6382f5bf9 -->):
staged locally so parallel contributors don't block each other; whole-repo where the gate is the wall.
A whole-repo **pre-commit** would deadlock — don't; that's what pre-push is for.

**There is only ONE pin, and it is not here.** Both server-side examples *derive* the recipe version
from your `darnlink-gate.json`'s `ref`, so bumping that one file moves both of them at once. (The
local hooks are a slightly different story: they `exec darnlink-gate` off your `PATH`, so `ref` moves
the *CLI* they run but not the recipe script itself — that one is deployed, not fetched per run.)

This paragraph used to say "keep them in sync, bump both together", and that is precisely how they
rotted. Measured against the tags on the day this changed: the Actions example was pinned at `v0.20.4`
with **3** releases published since, and the Jenkins one at `v0.7.0` with **23** — and that `v0.7.0`
is 23 days old, in a project 34 days old. Staleness here is counted in releases, not in months.
**Nothing fails when two copies of a version number drift.** If you copy
these into a repo, do not reintroduce a literal tag.

The derivation reads the `ref` **key** rather than grepping the file for something version-shaped —
a version string anywhere else in the json (an excluded path, say) would otherwise win silently,
which is the very failure the step exists to prevent. It takes whatever follows the last `@`, so a
tag, a branch and a SHA all work, and an `@` in the host (`git+ssh://git@github.com/…`) does not
confuse it. **One shape it does not cover:** a `ref` with *no* `@version` at all. `uvx` accepts that
(it means the default branch) and the derivation cannot — over ssh it yields a host fragment instead
of failing, and the `curl -f` turns it into a 404 one step later. Pin a version in `ref`.

**Raising to fail-closed links (`mode=max`)** is a one-line change in `darnlink-gate.json`
(`"mode": "max"`) once the repo's gap is 0 — the hooks and CI here need no edit. Follow
[`../../docs/elevating-your-link-gate.md`](../../docs/elevating-your-link-gate.md) <!-- uuid: e95eaed1-9866-4c48-a0d7-99a6382f5bf9 --> to get the gap to 0 first.
