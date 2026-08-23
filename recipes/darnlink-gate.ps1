# darnlink-gate.ps1 — Windows sibling of scripts/darnlink-gate (same generic darnlink quality-gate).
#
# See the bash version for the full rationale. Same contract: read-only; config in darnlink-gate.json
# (ref/excludes/ignore_blocks/mode/scope) with env overrides (DARNLINK_REF, DARNLINK_GATE_MODE,
# DARNLINK_GATE_SCOPE). MODE picks which axes gate — a one-way ratchet (repair ⊂ check ⊂ max):
#   mode=repair → integrity only (a strict-only failure, 3, is treated as clean);
#   mode=check  → integrity + strict, via `darnlink check` (stable 0/2/3 contract);
#   mode=max    → integrity + strict + create-frontmatter (fail-closed links). Runs BOTH `check` AND
#                 `darnlink . --robustify --create-frontmatter` (dry-run) — check has no create-fm axis
#                 and the bare pass has no integrity axis, so max unions them. WHOLE-REPO only; the
#                 staged pre-commit stays at strict by design (see the bash version §7 note).
# scope=staged filters `darnlink check --json` by `git diff --cached` (Option B — darnlink stays
# git-agnostic); refuses --write.
#
# FAIL-OPEN by default (an offline commit must not be bricked) — set DARNLINK_GATE_FAIL_CLOSED=1 (or
# "fail_closed": true in the json) in CI, where the gate IS the wall and failing open would mean a
# GREEN build with zero files validated. Exit: 0 clean · 2 integrity · 3 strict · 1 usage / max
# findings · 4 could-not-gate (fail-closed only).
$ErrorActionPreference = "Stop"

$root = (git rev-parse --show-toplevel 2>$null)
if (-not $root) { $root = (Get-Location).Path }
$root = $root.Trim()
Set-Location $root

# --- config (JSON, all optional); env wins over file ---
$cfg = @{}
$cfgPath = Join-Path $root "darnlink-gate.json"
if (Test-Path $cfgPath) { try { $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json } catch { $cfg = @{} } }
function CfgOr($key, $default) { if ($cfg.$key) { return $cfg.$key } else { return $default } }

$ref   = if ($env:DARNLINK_REF)        { $env:DARNLINK_REF }        else { CfgOr 'ref' 'git+https://github.com/txemi/darnlink@v0.7.0' }
$mode  = if ($env:DARNLINK_GATE_MODE)  { $env:DARNLINK_GATE_MODE }  else { CfgOr 'mode' 'check' }
$scope = if ($env:DARNLINK_GATE_SCOPE) { $env:DARNLINK_GATE_SCOPE } else { CfgOr 'scope' 'repo' }
# FAIL-CLOSED (parity with the bash recipe). Fails OPEN by default — right for pre-commit, DANGEROUS
# in CI, where a transient network/PyPI hiccup would give a GREEN build with zero files validated.
# Normalise: the json may carry a real boolean, and 'false'/'no'/'off'/0 must all mean OFF (a naive
# truthiness test would arm it for the very consumer asking to turn it off).
$rawFC = if ($null -ne $env:DARNLINK_GATE_FAIL_CLOSED) { $env:DARNLINK_GATE_FAIL_CLOSED } else { CfgOr 'fail_closed' '' }
$failClosed = -not ([string]::IsNullOrWhiteSpace([string]$rawFC) -or
                    ([string]$rawFC).Trim().ToLower() -in @('0','false','no','off'))

# ONE place decides what to do when the gate could NOT run: skip (default) or abort red (CI).
# Never "green without validating", which is the expensive silent failure.
function Invoke-Bail([string]$reason) {
  if ($failClosed) {
    # NOT Write-Error: with $ErrorActionPreference = "Stop" it raises a terminating error and the
    # script would die with exit 1 — never reaching the `exit 4` that tells CI "could not gate".
    [Console]::Error.WriteLine("darnlink-gate: $reason -> FAILING (fail-closed is on: nothing was validated).")
    exit 4
  }
  Write-Warning "darnlink-gate: $reason -> SKIP; CI covers the wall."
  exit 0
}
$excludes     = @(CfgOr 'excludes' @())
$ignoreBlocks = @(CfgOr 'ignore_blocks' @())
# WEB (opt-in, mode=max): add a `web-check --online` pass — cross-repo links to OTHER GitHub repos must
# resolve to the destination's uuid (read online). ⚠️ PUBLIC destinations need a token TOO — not for
# permission but for QUOTA: anonymous API calls are 60/h per public IP. Without one the pass reports
# web_unverifiable (a warning), which reads like "nothing to check" and can be a FALSE GREEN: an
# un-anchored web link is only discoverable if the destination can be READ. Fail-closed on a broken
# public web link. Same normalise dance.
$rawWeb = if ($null -ne $env:DARNLINK_GATE_WEB) { $env:DARNLINK_GATE_WEB } else { CfgOr 'web' '' }
$web = -not ([string]::IsNullOrWhiteSpace([string]$rawWeb) -or
             ([string]$rawWeb).Trim().ToLower() -in @('0','false','no','off'))
# OWN_WEB (opt-in, needs `web`): the owners you control. A destination owned by one of them whose .md
# has no uuid stops being "someone else's problem" and becomes a gate failure - feature 016. A LIST of
# names, never a sentinel: `own_web_from_origin` is its own key precisely so an owner literally called
# `origin` stays expressible, the same reason the CLI has a flag instead of `--own auto`.
# Read by PRESENCE, not by truthiness, for the same reason as `own_web_max` below: PowerShell unwraps
# a one-element array, so `["" ]` is $false to CfgOr and would come back as "absent" — losing the very
# entry the empty-entry warning exists to name.
$ownWeb = @(if ($cfg -and $cfg.PSObject.Properties.Name -contains 'own_web') { $cfg.own_web } else { @() })
$rawOWFO = if ($null -ne $env:DARNLINK_GATE_OWN_WEB_FROM_ORIGIN) { $env:DARNLINK_GATE_OWN_WEB_FROM_ORIGIN } else { CfgOr 'own_web_from_origin' '' }
$ownWebFromOrigin = -not ([string]::IsNullOrWhiteSpace([string]$rawOWFO) -or
                          ([string]$rawOWFO).Trim().ToLower() -in @('0','false','no','off'))

# Feature 017 (opt-in, needs `web`): also watch the destinations a mermaid diagram carries in its
# `click` directives. ABSENT MEANS OFF, per repository. Report-only: never anchored.
$rawIM = if ($null -ne $env:DARNLINK_GATE_INCLUDE_MERMAID) { $env:DARNLINK_GATE_INCLUDE_MERMAID } else { CfgOr 'include_mermaid' '' }
$includeMermaid = -not ([string]::IsNullOrWhiteSpace([string]$rawIM) -or
                        ([string]$rawIM).Trim().ToLower() -in @('0','false','no','off'))
# A budget, so the rung is adoptable before a repo reaches zero. Non-numeric counts as ABSENT, never as
# infinite: silently WIDENING an allowance is the one direction a config typo must not be able to go.
# NOT CfgOr here: it tests truthiness, and PowerShell reads the JSON `0` as [int]0, which is $false —
# so `own_web_max: 0` silently became "absent". That is the one value whose distinction from absent is
# the entire point of the budget, and it would have diverged from bash, which passes it. Read by
# PRESENCE instead.
$rawOWM = if ($null -ne $env:DARNLINK_GATE_OWN_WEB_MAX) { $env:DARNLINK_GATE_OWN_WEB_MAX }
          elseif ($cfg -and $cfg.PSObject.Properties.Name -contains 'own_web_max') { $cfg.own_web_max }
          else { '' }
$ownWebMax = ''
if (-not [string]::IsNullOrWhiteSpace([string]$rawOWM)) {
  # `[0-9]` and no Trim, to match the bash recipe character for character: `\d` in .NET also matches
  # Unicode digits, and trimming here would accept ' 3 ' where bash rejects it.
  if (([string]$rawOWM) -match '^[0-9]+$') { $ownWebMax = [string]$rawOWM }
  else { Write-Warning "darnlink-gate: own_web_max='$rawOWM' is not a non-negative integer - ignoring it." }
}
# CREATE_README (opt-in, mode=max): also run --create-readme — a directory link whose target folder has
# no README (no uuid) FAILS the gate (dry-run detects it; fix with --create-readme --write).
$rawCR = if ($null -ne $env:DARNLINK_GATE_CREATE_README) { $env:DARNLINK_GATE_CREATE_README } else { CfgOr 'create_readme' '' }
$createReadme = -not ([string]::IsNullOrWhiteSpace([string]$rawCR) -or
                      ([string]$rawCR).Trim().ToLower() -in @('0','false','no','off'))

# F4: `own_web` rides on `web` and on mode=max. Configured where the pass never runs it is a silent
# no-op that READS like protection - exactly what the CLI refuses to do with `--own-max` and no owners.
if (($ownWeb.Count -gt 0 -or $ownWebFromOrigin -or -not [string]::IsNullOrEmpty($ownWebMax)) -and
    ((-not $web) -or $mode -ne 'max')) {
  $webShown = if ($web) { '1' } else { 'off' }
  Write-Warning "darnlink-gate: own_web* is configured but the web pass does not run here (web=$webShown,"
  Write-Warning "  mode=$mode - it needs web on AND mode=max). The 016 rule is NOT being applied."
}

# --- guard: read-only. Never pass --write through. ---
if ($args -contains '--write') {
  Write-Error "darnlink-gate: refusing --write (read-only gate; robustify by hand: uvx --from $ref darnlink . --robustify --write)."
  exit 1
}

# --- ensure uvx (installer leaves it in ~\.local\bin); fail OPEN if absent ---
if (-not (Get-Command uvx -ErrorAction SilentlyContinue)) {
  $uvBin = Join-Path $env:USERPROFILE ".local\bin"
  if (Test-Path (Join-Path $uvBin "uvx.exe")) { $env:Path = "$uvBin;$env:Path" }
  else { Invoke-Bail "uvx not found" }
}

$dlArgs = @()
foreach ($e in $excludes)     { if ($e) { $dlArgs += @('--exclude', $e) } }
foreach ($b in $ignoreBlocks) { if ($b) { $dlArgs += @('--ignore-block', $b) } }

# Pre-flight: can uvx BUILD+RUN darnlink at this ref? darnlink's exit codes (0/1/2/3) overlap a uvx
# fetch failure, so confirm reachability first; if not -> fail OPEN (don't brick a commit; CI covers it).
& uvx --from $ref darnlink --help *> $null
if ($LASTEXITCODE -ne 0) { Invoke-Bail "can't run darnlink at $ref (bad ref / no network)" }

if ($scope -ne 'staged') {
  # ---- whole-repo (the wall): darnlink's own exit code is the gate ----
  if ($mode -eq 'max') {
    # LEVEL 3 = check (integrity + strict) UNION create-frontmatter. `check` has no create-frontmatter
    # axis; the bare `--robustify --create-frontmatter` DROPS integrity (never runs plan_repairs — a
    # broken robust link would sail through). So run BOTH dry-run passes and fail if either does — a
    # true superset of check. Both read-only.
    & uvx --from $ref darnlink check . @dlArgs @args
    $rc = $LASTEXITCODE
    if ($rc -eq 0) {
      $maxArgs = @('--robustify','--create-frontmatter')
      if ($createReadme) { $maxArgs += '--create-readme' }   # directory targets need a README too
      & uvx --from $ref darnlink . @maxArgs @dlArgs @args
      $rc = $LASTEXITCODE
    }
    # WEB pass (opt-in, max only): EVERY web-check non-zero is fail-closed (0 = clean incl web_unverifiable/
    # offline; 3 = a plain web link not yet anchored — dry-run, could be robustified; 4 = broken public web
    # link) — none is the core's rc>3 "unreachable", so exit it directly, bypassing the bail below.
    # web-check takes the SAME --exclude + --ignore-block as the core (since 0.12.0) -> pass both so it
    # skips vendored clones / mirrors instead of fetching+anchoring web links inside them.
    if ($rc -eq 0 -and $web) {
      # web-check needs $GITHUB_TOKEN for BOTH kinds of destination: private ones for permission,
      # PUBLIC ones for quota (anonymous API = 60/h per public IP, shared by every machine behind the
      # same NAT). If not already set, read it from a read-only PAT file (default
      # ~/.config/github_token_ro; override DARNLINK_GATE_TOKEN_FILE).
      if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
        $tf = if ($env:DARNLINK_GATE_TOKEN_FILE) { $env:DARNLINK_GATE_TOKEN_FILE } else { Join-Path $env:USERPROFILE ".config/github_token_ro" }
        # PathType Leaf = a file, not a dir. try/catch so a read error can't terminate the gate under
        # $ErrorActionPreference='Stop' (missing token just leaves private destinations web_unverifiable).
        if (Test-Path $tf -PathType Leaf) {
          try { $env:GITHUB_TOKEN = (Get-Content $tf -Raw -ErrorAction Stop).Trim() } catch { }
        }
      }
      # SAY IT when the axis cannot actually verify — same wording as the bash recipe on purpose, so
      # the two surfaces cannot drift into telling the operator different stories.
      if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
        Write-Warning "darnlink-gate: web axis running WITHOUT a token -> anonymous 60/h-per-IP quota."
        Write-Warning "  An 'ok 0 | unverifiable N' from web-check in this run means COULD NOT LOOK,"
        Write-Warning "  not 'nothing to verify' - and it is indistinguishable from a repo with no"
        Write-Warning "  cross-repo links at all."
        Write-Warning "  THIS CAN BE A FALSE GREEN: an un-anchored web link is only discoverable if"
        Write-Warning "  the destination can be READ. Measured: without token rc=0, with token rc=3."
        Write-Warning "  Export GITHUB_TOKEN, and quote the token condition next to any web figure -"
        Write-Warning "  without it the number is not comparable between two runs, let alone two repos."
      }
      $webArgs = @()
      foreach ($e in $excludes)     { if ($e) { $webArgs += @('--exclude', $e) } }
      foreach ($b in $ignoreBlocks) { if ($b) { $webArgs += @('--ignore-block', $b) } }
      $ownPassed = $false
      $ownWebUsed = 0
      foreach ($o in $ownWeb) { if ($o) { $webArgs += @('--own', $o); $ownPassed = $true; $ownWebUsed++ } }
      if ($includeMermaid)                 { $webArgs += '--include-mermaid' }
      if ($ownWebFromOrigin)               { $webArgs += '--own-from-origin'; $ownPassed = $true }
      if (-not [string]::IsNullOrEmpty($ownWebMax)) { $webArgs += @('--own-max', $ownWebMax); $ownPassed = $true }
      # Same two warnings as the bash recipe, same wording: an owner entry that is present but empty
      # is a typo that makes the axis enforce less than the config claims, and it would go green.
      if ($ownWeb.Count -gt 0 -and $ownWebUsed -eq 0) {
        Write-Warning "darnlink-gate: own_web is set but every entry is empty - no ownership was applied."
      } elseif ($ownWebUsed -lt $ownWeb.Count) {
        Write-Warning "darnlink-gate: own_web has $($ownWeb.Count - $ownWebUsed) empty entry/entries out of"
        Write-Warning "  $($ownWeb.Count) - they were ignored, so fewer owners are enforced than the config lists."
      }
      & uvx --from $ref darnlink web-check . --online @webArgs
      $webRc = $LASTEXITCODE
      # EXIT 1 IS A USAGE ERROR, NOT A VERDICT ABOUT THE REPO, and feature 016 makes it reachable from
      # CONFIGURATION: own_web_max without own_web, an empty owner name, or own_web_from_origin in a
      # tree with no GitHub `origin`. Reporting it as a red gate would send someone hunting for broken
      # links that do not exist. Say what is wrong and drop the axis for this run.
      # Only when THIS RUN passed an own_* flag: uvx exits 1 on its own failures and an uncaught
      # Python exception exits 1 too, so an unconditional swallow would turn those green for a repo
      # that never adopted 016 — a worse guarantee than before this key existed. And it respects
      # fail_closed: in CI an axis that could not run is not a pass.
      if ($webRc -eq 1 -and $ownPassed) {
        Write-Warning "darnlink-gate: web-check rejected its own arguments (exit 1) - most likely a CONFIG"
        Write-Warning "  error rather than a finding about this repository. Check own_web /"
        Write-Warning "  own_web_from_origin / own_web_max in darnlink-gate.json. The web axis did NOT run."
        if ($failClosed) {
          Write-Warning "  fail_closed is on: an axis that could not run is not a pass. -> 4"
          $webRc = 4
        } else { $webRc = 0 }
      }
      exit $webRc
    }
  } else {
    & uvx --from $ref darnlink check . @dlArgs @args   # `darnlink check` → 0/2/3 (mode=check|repair)
    $rc = $LASTEXITCODE
  }
  if ($rc -gt 3) { Invoke-Bail "darnlink unreachable (rc=$rc)" }
  # mode=repair gates on integrity only: a strict-only failure (3) is clean.
  if ($mode -eq 'repair' -and $rc -eq 3) { exit 0 }
  exit $rc
}

# ---- staged scope (Option B): darnlink judges the whole tree; WE filter findings to staged files ----
# NOTE mode=max here behaves as strict (level 2), by design: the create-frontmatter axis needs
# whole-tree reasoning, and per the wall architecture the staged pre-commit stays fast — max is
# enforced at the whole-repo wall (pre-push / CI). See docs/elevating-your-link-gate.md §7.
$staged = @(git diff --cached --name-only --diff-filter=ACMR -- '*.md' 2>$null)
if (-not $staged) { Write-Output "darnlink-gate (staged): no staged .md — nothing to judge."; exit 0 }

$json = (& uvx --from $ref darnlink check . --json @dlArgs 2>$null | Out-String)
$rc = $LASTEXITCODE
if ($rc -gt 3 -or -not $json.Trim()) { Invoke-Bail "(staged) darnlink unreachable (rc=$rc)" }

$data = $json | ConvertFrom-Json
$stagedSet = [System.Collections.Generic.HashSet[string]]::new()
foreach ($p in $staged) { [void]$stagedSet.Add(([IO.Path]::GetFullPath((Join-Path $root $p)))) }
function Hits($axis) { @($data.$axis.findings | Where-Object { $stagedSet.Contains(([IO.Path]::GetFullPath($_.file))) }) }
$integ  = Hits 'integrity'
$strict = if ($mode -eq 'repair') { @() } else { Hits 'strict' }   # mode=repair gates on integrity only
foreach ($f in $integ)  { Write-Output "  [integrity/$($f.kind)] $($f.file): $($f.detail)" }
foreach ($f in $strict) { Write-Output "  [strict/$($f.kind)] $($f.file): $($f.detail)" }
if ($integ)  { Write-Output "darnlink-gate (staged): integrity failure in a file you're committing."; exit 2 }
if ($strict) { Write-Output "darnlink-gate (staged): un-anchored plain link in a file you're committing (anchor it: uvx --from $ref darnlink . --robustify --write)."; exit 3 }
Write-Output "darnlink-gate (staged): clean."; exit 0
