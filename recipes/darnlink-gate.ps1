# darnlink-gate.ps1 — Windows sibling of scripts/darnlink-gate (same generic darnlink quality-gate).
#
# See the bash version for the full rationale. Same contract: read-only; config in darnlink-gate.json
# (ref/excludes/ignore_blocks/mode/scope) with env overrides (DARNLINK_REF, DARNLINK_GATE_MODE,
# DARNLINK_GATE_SCOPE); mode=check → `darnlink check` (both axes, 0/2/3), mode=repair → integrity only;
# scope=staged filters `darnlink check --json` by `git diff --cached` (Option B — darnlink stays
# git-agnostic); fail-open on network; refuses --write. Exit 0/2/3/1.
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
  else { Write-Warning "darnlink-gate: uvx not found -> SKIP (install uv; CI covers the wall)."; exit 0 }
}

$dlArgs = @()
foreach ($e in $excludes)     { if ($e) { $dlArgs += @('--exclude', $e) } }
foreach ($b in $ignoreBlocks) { if ($b) { $dlArgs += @('--ignore-block', $b) } }

# Pre-flight: can uvx BUILD+RUN darnlink at this ref? darnlink's exit codes (0/1/2/3) overlap a uvx
# fetch failure, so confirm reachability first; if not -> fail OPEN (don't brick a commit; CI covers it).
& uvx --from $ref darnlink --help *> $null
if ($LASTEXITCODE -ne 0) { Write-Warning "darnlink-gate: can't run darnlink at $ref (bad ref / no network) -> SKIP; CI covers the wall."; exit 0 }

if ($scope -ne 'staged') {
  # ---- whole-repo (the wall): darnlink's own exit code is the gate ----
  if ($mode -eq 'repair') { & uvx --from $ref darnlink . @dlArgs @args }
  else                    { & uvx --from $ref darnlink check . @dlArgs @args }
  $rc = $LASTEXITCODE
  if ($rc -gt 3) { Write-Warning "darnlink-gate: darnlink unreachable (rc=$rc) -> SKIP; CI covers it."; exit 0 }
  exit $rc
}

# ---- staged scope (Option B): darnlink judges the whole tree; WE filter findings to staged files ----
$staged = @(git diff --cached --name-only --diff-filter=ACMR -- '*.md' 2>$null)
if (-not $staged) { Write-Output "darnlink-gate (staged): no staged .md — nothing to judge."; exit 0 }

$json = (& uvx --from $ref darnlink check . --json @dlArgs 2>$null | Out-String)
$rc = $LASTEXITCODE
if ($rc -gt 3 -or -not $json.Trim()) { Write-Warning "darnlink-gate (staged): darnlink unreachable (rc=$rc) -> SKIP; CI covers the wall."; exit 0 }

$data = $json | ConvertFrom-Json
$stagedSet = [System.Collections.Generic.HashSet[string]]::new()
foreach ($p in $staged) { [void]$stagedSet.Add(([IO.Path]::GetFullPath((Join-Path $root $p)))) }
function Hits($axis) { @($data.$axis.findings | Where-Object { $stagedSet.Contains(([IO.Path]::GetFullPath($_.file))) }) }
$integ  = Hits 'integrity'
$strict = Hits 'strict'
foreach ($f in $integ)  { Write-Output "  [integrity/$($f.kind)] $($f.file): $($f.detail)" }
foreach ($f in $strict) { Write-Output "  [strict/$($f.kind)] $($f.file): $($f.detail)" }
if ($integ)  { Write-Output "darnlink-gate (staged): integrity failure in a file you're committing."; exit 2 }
if ($strict) { Write-Output "darnlink-gate (staged): un-anchored plain link in a file you're committing (anchor it: uvx --from $ref darnlink . --robustify --write)."; exit 3 }
Write-Output "darnlink-gate (staged): clean."; exit 0
