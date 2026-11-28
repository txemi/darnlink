# Feature Specification: a destination you own must be verifiable (`--own-verifiable`)

**Feature Branch**: `021-own-web-verifiable`

**Created**: 2026-11-28

**Status**: Implemented

**Input**: feature 016 named a second rung and deliberately left it out: *"a destination you own must
be **verifiable at all**"* (016 §The second rung). Today a cross-repo link to one of your own
repositories whose destination cannot be read — no token, a rejected token, a repository the token
cannot see, a network failure — is reported `web_unverifiable` and the run exits 0. In CI that is a
false green: the gate runs with a read-only token for its own forge precisely so that it can check
those links, and a link it could not check passes as if it had been. For a destination you own, "I
could not check" is a **provisioning failure** (a missing or under-scoped token, a runner that cannot
reach the forge), not an external limit.

This feature adds that rung, **off by default**, exactly as 016 said it must ship.

---

## Why off by default, and why not folded into 016's rule

016 explains it: turning this on together with the base rule reproduces the wall of false breaks
that 013's tokenless-404 carve-out was written to prevent. A developer laptop, or a pre-commit hook,
usually has no token; every owned link would fail there. The rung is for the surface that **does**
have a token and is expected to use it — CI. So it is a separate flag, and a separate recipe key,
switched on where the token is provisioned.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Flag | **`--own-verifiable`** on `web-check`, boolean, off by default | 016: a separate rung, never a silent widening of the base rule |
| Needs an owner set? | **Yes.** Without `--own` / `--own-from-origin` it is a usage error, exit 1 | same argument as `--own-max` (016 FR-012): a rule that applies to no destination is a no-op that reads like protection |
| Needs `--online`? | **Yes**, exit 1 otherwise | 016 FR-017: the offline branch ignores it entirely |
| What becomes a failure | a **recognised file link** whose owner is **owned** and whose destination **could not be read** (FR-003) | everything else is either already a verdict or not about provisioning |
| New kind | **`web_own_unverifiable`** | a consumer of `--json` must be able to tell it from the informational `web_unverifiable` it replaces |
| Exit code | **4** | see §Exit code |
| Budgeted by `--own-max`? | **No** | see §Not budgeted |
| Recipe key | **`own_web_verifiable`** (boolean) | the family is `own_web`, `own_web_from_origin`, `own_web_max`; the recipes' "own_web* is configured but the web pass does not run" warning names the family by that prefix |

### Exit code: 4, not 1 and not 3

- **3** means "a plain link darnlink can anchor for you — re-run with `--write`". Nothing here can be
  fixed by `--write`; promising it would be false, the same argument 016 makes for `web_own_no_uuid`.
- **1** is a usage error, decided **before any fetch** from the command line alone. This finding is
  decided per link, after the fetch, and a run can carry it next to other findings. Reporting it as 1
  would also collide with the recipes' reading of exit 1 as "the configuration was rejected, the web
  axis did NOT run" — which under fail-open turns the run **green**: exactly the false pass this
  feature removes.
- **4** is the integrity exit: "a link the gate relies on is not verified". It is fail-closed in both
  recipes (`RC_IS_FINAL`), it is what `web_mismatch`, `web_not_found` and `web_own_no_uuid` already
  use, and an unverifiable owned link is the same kind of statement: this link is not known to be
  good. That makes 4 the only code a gate already treats as "the repository failed".

### Not budgeted

`--own-max` budgets per-destination edits: each `web_own_no_uuid` needs a change in another
repository, so a repo cannot reach zero in one step. This finding is the opposite: one provisioning
fix (a token with the right scope, a route to the forge) clears every finding at once. A budget here
would only hide the one moment the provisioning broke. The two counts stay separate in the report.

## Functional requirements

- **FR-001** Without `--own-verifiable`, every output is identical to the previous release, except
  for two additive keys in the `--json` summary object (FR-009).
- **FR-002** `--own-verifiable` without an owner set (after `--own` values are stripped and
  `--own-from-origin` is resolved) MUST exit 1 with a message naming the missing flags, before any
  fetch. Without `--online` it MUST exit 1 as well (016 FR-017's message lists it).
- **FR-003** With the flag, a link MUST be reported **`web_own_unverifiable`** when all of these hold:
  - it **parses as a file link**: a GitHub `blob`/`raw` URL, or a `src`/`raw` file URL on a
    `--forgejo` instance (018 FR-003) — anything `parse_github_url` returns `None` for is out;
  - its **owner is owned** (016 FR-001, case-folded; applies to Forgejo links too, 018 FR-006);
  - its file does **not** carry `darnlink-ignore-file` (003) or `darnlink-ignore-links` (006) —
    the same by-kind filter 016 FR-014 applies to `web_own_no_uuid`: the link degrades to
    `web_unverifiable`, reported, not silent;
  - the destination **could not be read**, which is exactly one of:

    | Status from the fetcher | Cause in the message | Fix in the message |
    |---|---|---|
    | 401/403, no token | anonymous request rejected, `<VAR>` is not set | export `<VAR>` with a token that can read `<owner>/<repo>` |
    | 401/403, with a token | the token in `<VAR>` was rejected | provision `<VAR>` with a token that can read `<owner>/<repo>` |
    | `-2` (404 in a repository the token cannot read) | 404 in a repository the token in `<VAR>` cannot read | provision `<VAR>` with a token that can read `<owner>/<repo>` |
    | 404, no token | 404 without a token: a private repository cannot be told from a missing file | export `<VAR>` with a token that can read `<owner>/<repo>` |
    | `-1` (network failure, after `default_fetcher`'s retries; for Forgejo, every declared name unreachable) | no answer from the server | make `<server>` reachable from where this runs |
    | any other non-200 left after the retries (429, 5xx) | fetch failed (status N) | make `<server>` answer from where this runs |

    `<VAR>` is the destination's own variable, `GITHUB_TOKEN` or `FORGEJO_TOKEN` (018 FR-008's
    rule: name the variable that would fix it, and never the other forge's). `<server>` is the API
    host for GitHub, the declared instance's first name for Forgejo.
- **FR-004** The message MUST name owner, repo and path, the cause, and the fix from FR-003's
  table, and say that this is provisioning, not a broken link. It MUST NOT suggest `--write`.
- **FR-005** `web_own_unverifiable` MUST set the exit code to **4**, whatever `--own-max` says.
- **FR-006** **Nothing that was answered changes.** These keep exactly today's kind and exit
  contribution, owned or not, with or without the flag:
  - a **200**, in every variant: `web_ok`, `web_anchor`, `web_mismatch`, `web_own_no_uuid`,
    `web_own_exempt`, and the `web_unverifiable` cases decided on a 200 (non-`.md`, SHA-pinned,
    invalid frontmatter, a diagram link);
  - a **404 with a token** in a readable repository: `web_not_found`, or `web_unverifiable` when it
    is pending on the default branch — both are answers about the destination, not failures to get
    one;
  - **`-3`** (the client refused to send the URL): a defect of the link itself, which no token or
    route can fix;
  - every **unrecognised URL** (a PR page, an issue, a repository home page, a non-forge URL).
  Because every status in FR-003's table is one that today yields `web_unverifiable` for every link
  — exempt, diagram or plain — the new kind can never replace a failure that already exists, so
  nothing is counted twice.
- **FR-007** 016's exemption marker (`<!-- darnlink-own-exempt -->`) does **not** exempt from this
  finding. It exempts three verdicts that are reached on a 200 (016 FR-011), and 016's §Precedence
  makes status decide first: an exempt link whose destination 404s is `web_not_found`, and one that
  cannot be read at all is, likewise, not verified.
- **FR-008** Deciding the finding MUST cost no extra request: it reads the status the fetch already
  returned.
- **FR-009** `--json` MUST carry the kind under its own `kind`, a `web_own_unverifiable` count, and
  an `own_verifiable` key with the flag's value (so a run without the flag is distinguishable in the
  payload, the precedent of 016's `own_max`). The text report MUST count it in the summary line
  (`| own-unverifiable N`, printed only when non-zero, so FR-001 holds there) and list each one.

## Gate recipes

- **`own_web_verifiable`** (boolean): normalised exactly like the other boolean keys — the closed
  list of spellings, `bad_flag` (bash) / `Read-Flag` (PowerShell) on anything else, environment
  override `DARNLINK_GATE_OWN_WEB_VERIFIABLE`. When true, the web pass gets `--own-verifiable` and
  the flag counts as an `own_*` flag for the recipes' reading of exit 1 as configuration.
- Configured where the web pass does not run (no `web`, or `mode` other than `max`), it is included
  in the existing "own_web* is configured but the web pass does not run here" warning.
- Configured with no owner key (`own_web` empty or absent, no `own_web_from_origin`), the recipe says
  so on stderr before running, and web-check's exit 1 is then reported as configuration, with the
  same `fail_closed` handling `own_web_max` without owners already has.
- `gate_config.py` lists the key (kind `flag`), so `gate-config` validates it and the generated
  `gate_config.schema.json` documents it.
- **Both recipes.** `recipes/darnlink-gate.ps1` supports the web-axis keys (since the 0.31 parity
  work), so the key is wired there with the same argument order and the same messages. The parity
  table (`tests/test_recipe_parity.py`) covers it through the boolean `"disabled"` case.

## Out of scope

- **Making a malformed owned URL (`-3`) a failure.** It is a real defect, but of the link, not of the
  provisioning; it belongs with a rule about link syntax, not with this one.
- **A per-instance or per-owner switch.** One flag for the run: the token condition is per run too.
- **Distinguishing the anonymous rate limit from a missing permission on GitHub.** Both are fixed by
  the same token, so the message does not need to tell them apart.

## Tests

`tests/test_own_web_verifiable.py` (the fetch layer injected, hosts under `example.test`, the network
never touched) and the `own_web_verifiable` wiring tests in `tests/test_recipe_gate.py`, asserted on
the invocation as the 016 keys are, plus the parity table for the boolean case.
