# darnlink-gate.ps1 — Windows sibling of scripts/darnlink-gate (same generic darnlink quality-gate).
#
# See the bash version for the full rationale. Same contract: read-only; config in darnlink-gate.json
# (ref/excludes/ignore_blocks/mode/scope) with env overrides (DARNLINK_REF, DARNLINK_GATE_MODE,
# DARNLINK_GATE_SCOPE). It ALWAYS runs `darnlink check` (stable 0/2/3 contract); MODE only picks which
# axes gate: mode=check → integrity + strict both gate; mode=repair → integrity only (a strict-only
# failure, 3, is treated as clean). scope=staged filters `darnlink check --json` by `git diff --cached`
# (Option B — darnlink stays git-agnostic); refuses --write.
#
# FAIL-OPEN by default (an offline commit must not be bricked) — set DARNLINK_GATE_FAIL_CLOSED=1 (or
# "fail_closed": true in the json) in CI, where the gate IS the wall and failing open would mean a
# GREEN build with zero files validated. Exit: 0 clean · 2 integrity · 3 strict · 1 usage ·
# 4 could-not-gate (fail-closed only).
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

$ref   = if ($env:DARNLINK_REF)        { $env:DARNLINK_REF }        else { CfgOr 'ref' 'git+https://github.com/txemi/darnlink@v0.5.0' }
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
  & uvx --from $ref darnlink check . @dlArgs @args   # always `check` → stable 0/2/3, regardless of MODE
  $rc = $LASTEXITCODE
  if ($rc -gt 3) { Invoke-Bail "darnlink unreachable (rc=$rc)" }
  # mode=repair gates on integrity only: a strict-only failure (3) is clean.
  if ($mode -eq 'repair' -and $rc -eq 3) { exit 0 }
  exit $rc
}

# ---- staged scope (Option B): darnlink judges the whole tree; WE filter findings to staged files ----
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
