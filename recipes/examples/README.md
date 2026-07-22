# darnlink-gate — complete, copy-paste examples

Runnable versions of the four pieces from [`../README.md`](../README.md#adopt-it-in-a-repo-the-wall-in-4-pieces).
Each file is a whole, working artifact — not a snippet to assemble — because assembling the CI one
wrong yields a wall that fails **open** (green build, nothing validated). They wire the same generic
recipe ([`../darnlink-gate`](../darnlink-gate)) at the scope that fits each layer.

| File | Layer | Scope | Fail mode |
|---|---|---|---|
| [`pre-commit`](pre-commit) | local, per-commit | **staged** (fast; no cross-session deadlock) | open |
| [`pre-push`](pre-push) | local wall | **whole repo** | open (flip to closed inside) |
| [`github-actions-darnlink-gate.yml`](github-actions-darnlink-gate.yml) | server wall | **whole repo** | **closed** |
| [`Jenkinsfile-stage.groovy`](Jenkinsfile-stage.groovy) | server wall (self-hosted) | **whole repo** | **closed** |

**The scope split is deliberate** (see [`../../docs/elevating-your-link-gate.md §7`](../../docs/elevating-your-link-gate.md)):
staged locally so parallel contributors don't block each other; whole-repo where the gate is the wall.
A whole-repo **pre-commit** would deadlock — don't; that's what pre-push is for.

**Keep the pinned tag in sync.** Every example pins `@v0.7.0`; that must match your
`darnlink-gate.json`'s `ref`. Bump both together.

**Raising to fail-closed links (`mode=max`)** is a one-line change in `darnlink-gate.json`
(`"mode": "max"`) once the repo's gap is 0 — the hooks and CI here need no edit. Follow
[`../../docs/elevating-your-link-gate.md`](../../docs/elevating-your-link-gate.md) to get the gap to 0 first.
