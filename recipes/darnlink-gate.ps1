# darnlink-gate.ps1 — Windows sibling of scripts/darnlink-gate (same generic darnlink quality-gate).
#
# See the bash version for the full rationale. THE BASH RECIPE IS THE REFERENCE: same keys, same
# closed lists, same case-sensitive comparisons, same axes, same exit codes. Same contract:
# read-only; config in darnlink-gate.json (every key of src/darnlink/gate_config.py KEYS but
# recipe_sha256) with env overrides (DARNLINK_REF, DARNLINK_GATE_MODE, DARNLINK_GATE_SCOPE, ...).
# MODE picks which axes gate — a one-way ratchet (repair ⊂ check ⊂ max):
#   mode=repair → integrity only (a strict-only failure, 3, is treated as clean);
#   mode=check  → integrity + strict, via `darnlink check` (stable 0/2/3 contract);
#   mode=max    → integrity + strict + create-frontmatter (fail-closed links). Runs BOTH `check` AND
#                 `darnlink . --robustify --create-frontmatter` (dry-run) — check has no create-fm axis
#                 and the bare pass has no integrity axis, so max unions them. WHOLE-REPO only; the
#                 staged pre-commit stays at strict by design (see the bash version §7 note).
# `mode` and `scope` are compared CASE-SENSITIVELY, as in bash: "MAX" is not max (it runs check) and
# "Staged" is not staged (it judges the whole repo). PowerShell's -eq ignores case, which is how the
# two recipes used to run different gates from the same file.
# scope=staged filters `darnlink check --json` by `git diff --cached` (Option B — darnlink stays
# git-agnostic); refuses --write.
#
# FAIL-OPEN by default (an offline commit must not be bricked) — set DARNLINK_GATE_FAIL_CLOSED=1 (or
# "fail_closed": true in the json) in CI, where the gate IS the wall and failing open would mean a
# GREEN build with zero files validated. Exit: 0 clean · 2 integrity · 3 strict · 1 usage / max or
# create-readme or dangling findings / a config that does not parse / a flag that is not a boolean ·
# 4 could-not-gate (fail-closed only).
$ErrorActionPreference = "Stop"

$root = (git rev-parse --show-toplevel 2>$null)
if (-not $root) { $root = (Get-Location).Path }
$root = $root.Trim()
Set-Location -LiteralPath $root
# Set-Location does not move the PROCESS cwd, and [IO.Path]::GetFullPath resolves against that one:
# without this, a relative finding path from a run started in a subfolder would miss the staged set.
[Environment]::CurrentDirectory = $root

# --- config (JSON, all optional); env wins over file ---
# A config that EXISTS but does not parse is a hard error, in both fail modes — same as bash. This
# used to be `catch { $cfg = @{} }`: every key reverted to its default (an old pinned ref, mode=check,
# no excludes) and the gate reported a verdict about a policy written in no file. Green, and about
# nothing. It is not Invoke-Bail: CI would read the same broken file, so skipping is never right.
# Read as the bash recipe reads it: UTF-8, strictly, with an optional BOM. A UTF-16 file (what
# PowerShell 5.1 writes by default) is rejected there, so it is rejected here. And parsed strictly
# where the runtime can (System.Text.Json, PowerShell 7): ConvertFrom-Json alone accepts a trailing
# comma or a comment, which Python's json — the bash recipe's parser — refuses.
$cfgPath = Join-Path $root "darnlink-gate.json"
$cfg = $null
if (Test-Path -LiteralPath $cfgPath -PathType Leaf) {
  try {
    $bytes = [System.IO.File]::ReadAllBytes($cfgPath)
    $skip = if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { 3 } else { 0 }
    $text = (New-Object System.Text.UTF8Encoding($false, $true)).GetString($bytes, $skip, $bytes.Length - $skip)
    if ([string]::IsNullOrWhiteSpace($text)) { throw "the file is empty" }
    $strictJson = 'System.Text.Json.JsonDocument' -as [type]
    if (-not $strictJson) {
      try { Add-Type -AssemblyName System.Text.Json -ErrorAction Stop } catch { }
      $strictJson = 'System.Text.Json.JsonDocument' -as [type]
    }
    if ($strictJson) {
      $strictJson::Parse($text, (New-Object System.Text.Json.JsonDocumentOptions)).Dispose()
    } elseif ([regex]::Replace($text, '"(?:[^"\\]|\\.)*"', '""') -match ',\s*[}\]]') {
      # Windows PowerShell 5.1 has no System.Text.Json, and its ConvertFrom-Json may let a trailing
      # comma through. Strings blanked first, so a comma inside a value is not mistaken for one.
      throw "a trailing comma before a closing bracket"
    }
    $cfg = $text | ConvertFrom-Json
  } catch {
    [Console]::Error.WriteLine("darnlink-gate: $cfgPath exists but is not valid JSON -> FAILING.")
    [Console]::Error.WriteLine("  Nothing was validated. Every key would have silently reverted to its default,")
    [Console]::Error.WriteLine("  including the pinned version, mode and excludes. Parse error:")
    [Console]::Error.WriteLine("    $($_.Exception.Message)")
    exit 1
  }
}

# Is `key` in the file, spelled exactly so? Case-SENSITIVE, like the bash recipe's `d.get(key)`:
# PowerShell's own `$cfg.$key` ignores case, so `"MODE": "max"` used to be read here and not there.
function CfgHas([string]$key) {
  return ($null -ne $cfg) -and (@($cfg.PSObject.Properties.Name) -ccontains $key)
}

# A parsed JSON value rendered as the bash recipe's read_cfg renders it (Python's str()), so both
# recipes judge the SAME string: a JSON true is "True", 0.0 is "0.0" (PowerShell would say "0"), a
# list is its items joined by newlines, and a list with a non-string item is unreadable there (the
# join raises), so it is $null here and takes the default.
function ConvertTo-CfgString($v) {
  if ($v -is [System.Collections.IList]) {
    $items = @($v)
    foreach ($i in $items) { if ($i -isnot [string]) { return $null } }
    return ($items -join "`n")
  }
  if ($null -eq $v) { return $null }
  if ($v -is [bool]) { if ($v) { return 'True' } else { return 'False' } }
  if ($v -is [string]) { return $v }
  $inv = [System.Globalization.CultureInfo]::InvariantCulture
  if ($v -is [double] -or $v -is [single] -or $v -is [decimal]) {
    $s = ([double]$v).ToString('R', $inv)
    if ($s -cnotmatch '[.Ee]') { $s += '.0' }
    return $s
  }
  if ($v -is [System.ValueType]) { return [string]::Format($inv, '{0}', $v) }
  return '<object>'   # a JSON object: Python prints its repr, which is no flag, count or name either
}

# The string value of `key`, or $default when absent or null — bash's `$(read_cfg key default)`,
# trailing newlines stripped as `$(...)` strips them.
function CfgStr([string]$key, $default) {
  if (-not (CfgHas $key)) { return $default }
  $s = ConvertTo-CfgString ($cfg.PSObject.Properties[$key].Value)
  if ($null -eq $s) { return $default }
  return $s.TrimEnd("`n")
}

# A LIST key as bash's `mapfile -t X < <(read_cfg key "")` sees it. Assign it, never wrap it in @():
# the leading comma keeps an empty or one-element list from being unrolled on the way out.
function CfgList([string]$key) {
  $s = CfgStr $key ''
  if ($s -ceq '') { return ,@() }
  return ,@($s -split "`n")
}

# A BOOLEAN key takes one of a CLOSED list of spellings, compared after lower-casing: true, 1, yes,
# on / false, 0, no, off (and empty, which is absent). Same lists as the bash recipe's `case`s and as
# FLAG_ON / FLAG_OFF in src/darnlink/gate_config.py. Anything else is a config error and stops the
# gate, in both fail modes. It used to be "anything not on the off-list is ON", so
# `"fail_closed": "disabled"` armed the flag and nothing said a word. No Trim either: bash does not
# trim, so ' on' is not a boolean in either recipe.
function Read-Flag([string]$key, [string]$envName) {
  $fromEnv = [Environment]::GetEnvironmentVariable($envName)
  if ($fromEnv) { $v = $fromEnv; $src = "environment variable $envName" }
  else          { $v = CfgStr $key ''; $src = $cfgPath }
  $low = $v.ToLowerInvariant()
  if ($low -cin @('', '0', 'false', 'no', 'off')) { return $false }
  if ($low -cin @('1', 'true', 'yes', 'on'))      { return $true }
  [Console]::Error.WriteLine("darnlink-gate: $key='$v' (from $src) is not a boolean -> FAILING.")
  [Console]::Error.WriteLine("  Write true or false. Accepted, in any case: true, 1, yes, on / false, 0, no, off.")
  [Console]::Error.WriteLine("  Nothing was validated: an unknown value is not read as on, and not as off either.")
  exit 1
}

$ref   = if ($env:DARNLINK_REF)        { $env:DARNLINK_REF }        else { CfgStr 'ref' 'git+https://github.com/txemi/darnlink@v0.7.0' }
$mode  = if ($env:DARNLINK_GATE_MODE)  { $env:DARNLINK_GATE_MODE }  else { CfgStr 'mode' 'check' }
$scope = if ($env:DARNLINK_GATE_SCOPE) { $env:DARNLINK_GATE_SCOPE } else { CfgStr 'scope' 'repo' }
# FAIL-CLOSED (parity with the bash recipe). Fails OPEN by default — right for pre-commit, DANGEROUS
# in CI, where a transient network/PyPI hiccup would give a GREEN build with zero files validated.
$failClosed = Read-Flag 'fail_closed' 'DARNLINK_GATE_FAIL_CLOSED'

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
$excludes     = CfgList 'excludes'
$ignoreBlocks = CfgList 'ignore_blocks'
# WEB (opt-in, mode=max): add a `web-check --online` pass — cross-repo links to OTHER GitHub repos must
# resolve to the destination's uuid (read online). ⚠️ PUBLIC destinations need a token TOO — not for
# permission but for QUOTA: anonymous API calls are 60/h per public IP. Without one the pass reports
# web_unverifiable (a warning), which reads like "nothing to check" and can be a FALSE GREEN: an
# un-anchored web link is only discoverable if the destination can be READ. Fail-closed on a broken
# public web link.
$web = Read-Flag 'web' 'DARNLINK_GATE_WEB'
# OWN_WEB (opt-in, needs `web`): the owners you control. A destination owned by one of them whose .md
# has no uuid stops being "someone else's problem" and becomes a gate failure - feature 016. A LIST of
# names, never a sentinel: `own_web_from_origin` is its own key precisely so an owner literally called
# `origin` stays expressible, the same reason the CLI has a flag instead of `--own auto`.
# Read by PRESENCE and RAW, not through CfgList: the empty-entry warnings below need the entries the
# config actually lists, `[""]` included, which a flattened value cannot tell from an absent key.
$ownWeb = @(if (CfgHas 'own_web') { $cfg.own_web | Where-Object { $null -ne $_ } } else { @() })
# FORGEJO_WEB (opt-in, needs `web`): declared self-hosted Forgejo instances, one entry each, names
# comma-separated inside the entry - see the bash recipe. Read by presence, like own_web.
$forgejoWeb = @(if (CfgHas 'forgejo_web') { $cfg.forgejo_web | Where-Object { $null -ne $_ } } else { @() })
$ownWebFromOrigin = Read-Flag 'own_web_from_origin' 'DARNLINK_GATE_OWN_WEB_FROM_ORIGIN'

# The repo's DEFAULT BRANCH, for telling a link that is PENDING on it from one that is broken. A
# STRING, not a flag (a branch may be called `off`), so it is not Read-Flag. What cannot be a branch
# is a JSON boolean, rendered "True"/"False": refused, as in bash, and every real name kept.
$defaultBranch = if ($env:DARNLINK_GATE_DEFAULT_BRANCH) { $env:DARNLINK_GATE_DEFAULT_BRANCH } else { CfgStr 'default_branch' '' }
if ($defaultBranch -cin @('True', 'False')) {
  Write-Warning "darnlink-gate: default_branch=$defaultBranch looks like a JSON boolean, not a branch name -- ignoring it."
  Write-Warning "  Quote it (`"main`") if you meant a branch; remove the key to derive it from origin."
  $defaultBranch = ''
}

# Feature 017 (opt-in, needs `web`): also watch the destinations a mermaid diagram carries in its
# `click` directives. ABSENT MEANS OFF, per repository. Report-only: never anchored.
$includeMermaid = Read-Flag 'include_mermaid' 'DARNLINK_GATE_INCLUDE_MERMAID'
# A budget, so the rung is adoptable before a repo reaches zero. Non-numeric counts as ABSENT, never as
# infinite: silently WIDENING an allowance is the one direction a config typo must not be able to go.
# Through CfgStr, which reads by PRESENCE (a JSON `0` is the one value whose distinction from absent
# is the entire point of the budget) and renders 5.0 as "5.0", as bash does, so it is refused in both.
$rawOWM = if ($env:DARNLINK_GATE_OWN_WEB_MAX) { $env:DARNLINK_GATE_OWN_WEB_MAX } else { CfgStr 'own_web_max' '' }
$ownWebMax = ''
if ($rawOWM -cne '') {
  # `[0-9]`, `\z` and no Trim, to match the bash recipe character for character: `\d` in .NET also
  # matches Unicode digits, `$` also matches before a trailing newline, and trimming here would accept
  # ' 3 ' where bash rejects it.
  if ($rawOWM -cmatch '^[0-9]+\z') { $ownWebMax = $rawOWM }
  else { Write-Warning "darnlink-gate: own_web_max='$rawOWM' is not a non-negative integer - ignoring it." }
}
# CREATE_README (opt-in, ANY mode): also run --create-readme — a directory link whose target folder
# has no README (no uuid) FAILS the gate (dry-run detects it; fix with --create-readme --write).
$createReadme = Read-Flag 'create_readme' 'DARNLINK_GATE_CREATE_README'
# DANGLING (opt-in, default off): links whose target does not exist (feature 015), a SEPARATE axis,
# never folded into MODE. off | warn | added-lines | repo, with the bash recipe's synonyms; an unknown
# value is treated as off, with a warning — narrowing, never widening. See the bash recipe.
$danglingRaw = if ($env:DARNLINK_GATE_DANGLING) { $env:DARNLINK_GATE_DANGLING } else { CfgStr 'dangling' 'off' }
$dl = $danglingRaw.ToLowerInvariant()
$dangling = if     ($dl -cin @('off', '', '0', 'false', 'no'))           { 'off' }
            elseif ($dl -ceq 'warn')                                     { 'warn' }
            elseif ($dl -cin @('added-lines', 'added_lines'))            { 'added-lines' }
            elseif ($dl -cin @('repo', 'all', 'on', '1', 'true', 'yes')) { 'repo' }
            else {
              Write-Warning "darnlink-gate: unknown dangling=$danglingRaw (use off|warn|added-lines|repo) - treating as off."
              'off'
            }
# `dangling_max` turns `repo` into a BUDGET. A non-numeric value is 0 (strictest) on purpose.
$danglingMax = if ($env:DARNLINK_GATE_DANGLING_MAX) { $env:DARNLINK_GATE_DANGLING_MAX } else { CfgStr 'dangling_max' '0' }
if ($danglingMax -cnotmatch '^[0-9]+\z') {
  Write-Warning "darnlink-gate: dangling_max='$danglingMax' is not a non-negative integer - using 0."
  $danglingMax = '0'
}
$danglingMaxN = [double]$danglingMax
# CREATE_README_EXCLUDES: extra directory globs that apply ONLY to the create-readme pass, on top of
# `excludes` — so a `mirrors/` tree gets no invented README yet keeps its inbound links validated.
$createReadmeExcludes = CfgList 'create_readme_excludes'
$crExcludes = @($createReadmeExcludes | Where-Object { $_ })

# F4: `own_web` rides on `web` and on mode=max. Configured where the pass never runs it is a silent
# no-op that READS like protection - exactly what the CLI refuses to do with `--own-max` and no owners.
if (($ownWeb.Count -gt 0 -or $ownWebFromOrigin -or -not [string]::IsNullOrEmpty($ownWebMax)) -and
    ((-not $web) -or $mode -cne 'max')) {
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
# $HOME, not $env:USERPROFILE: the same directory on Windows, and defined under pwsh elsewhere too.
if (-not (Get-Command uvx -ErrorAction SilentlyContinue)) {
  $uvBin = Join-Path $HOME ".local\bin"
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

# The create-readme axis as its OWN dry-run pass, keeping only the `create_readme` findings, with
# create_readme_excludes layered on top of the global excludes. Returns the offender count, or 'ERR'
# if it could not be evaluated. Offenders go to stderr. Same pass, same argv as the bash recipe's
# create_readme_offenders. Its own $ErrorActionPreference: under "Stop", PowerShell 5.1 turns a native
# command's redirected stderr line into a terminating error.
function Get-CreateReadmeOffenders {
  $ErrorActionPreference = 'Continue'
  $crArgs = @($dlArgs)
  foreach ($e in $crExcludes) { $crArgs += @('--exclude', $e) }
  $json = (& uvx --from $ref darnlink . --robustify --create-frontmatter --create-readme @crArgs --json 2>$null | Out-String)
  $jrc = $LASTEXITCODE
  if ($jrc -gt 3 -or -not ([string]$json).Trim()) { return 'ERR' }
  try { $d = $json | ConvertFrom-Json } catch { return 'ERR' }
  $off = @($d.findings | Where-Object { $null -ne $_ -and $_.kind -ceq 'create_readme' })
  foreach ($f in $off) { [Console]::Error.WriteLine("  [create-readme] $($f.file): $($f.detail)") }
  return $off.Count
}

# The dangling axis, whole-repo: fills $script:dlFindings and returns $true, or $false if it could
# not be evaluated. Same pass as the bash recipe's dangling_findings.
function Get-DanglingFindings {
  $ErrorActionPreference = 'Continue'
  $json = (& uvx --from $ref darnlink check . --json @dlArgs 2>$null | Out-String)
  $jrc = $LASTEXITCODE
  if ($jrc -gt 3 -or -not ([string]$json).Trim()) { return $false }
  try { $d = $json | ConvertFrom-Json } catch { return $false }
  $script:dlFindings = @($d.dangling.findings | Where-Object { $null -ne $_ })
  return $true
}

if ($scope -cne 'staged') {
  # ---- whole-repo (the wall): darnlink's own exit code is the gate ----
  $rc = 0
  $rcIsFinal = $false   # the web verdict is fail-closed by contract: not re-read as "unreachable"
  $foldedCR = $false    # create_readme already covered by the max robustify pass
  if ($mode -ceq 'max') {
    # LEVEL 3 = check (integrity + strict) UNION create-frontmatter. `check` has no create-frontmatter
    # axis; the bare `--robustify --create-frontmatter` DROPS integrity (never runs plan_repairs — a
    # broken robust link would sail through). So run BOTH dry-run passes and fail if either does — a
    # true superset of check. Both read-only.
    $maxArgs = @('--robustify','--create-frontmatter')
    # create_readme FOLDS into this pass only with no create_readme_excludes (the legacy shape); with
    # them it moves to its own pass below, so those excludes never leak into robustify.
    if ($createReadme -and $crExcludes.Count -eq 0) { $maxArgs += '--create-readme'; $foldedCR = $true }
    & uvx --from $ref darnlink check . @dlArgs @args
    $rc = $LASTEXITCODE
    if ($rc -eq 0) {
      & uvx --from $ref darnlink . @maxArgs @dlArgs @args
      $rc = $LASTEXITCODE
    }
    # WEB pass (opt-in, max only): EVERY web-check non-zero is fail-closed (0 = clean incl web_unverifiable/
    # offline; 3 = a plain web link not yet anchored — dry-run, could be robustified; 4 = broken public web
    # link) — none is the core's rc>3 "unreachable", so it is marked final and bypasses the bail below.
    # web-check takes the SAME --exclude + --ignore-block as the core (since 0.12.0) -> pass both so it
    # skips vendored clones / mirrors instead of fetching+anchoring web links inside them.
    if ($rc -eq 0 -and $web) {
      # web-check needs $GITHUB_TOKEN for BOTH kinds of destination: private ones for permission,
      # PUBLIC ones for quota (anonymous API = 60/h per public IP, shared by every machine behind the
      # same NAT). If not already set, read it from a read-only PAT file (default
      # ~/.config/github_token_ro; override DARNLINK_GATE_TOKEN_FILE).
      if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
        $tf = if ($env:DARNLINK_GATE_TOKEN_FILE) { $env:DARNLINK_GATE_TOKEN_FILE } else { Join-Path $HOME ".config/github_token_ro" }
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
      # Same argument ORDER as the bash recipe, so the two build the same command line.
      $webArgs = @()
      $forgejoPassed = $false
      foreach ($fj in $forgejoWeb) { if ($fj) { $webArgs += @('--forgejo', $fj); $forgejoPassed = $true } }
      # Same file convention as GITHUB_TOKEN, under its OWN variable: one forge's credential is never
      # handed to the other.
      if ($forgejoPassed -and [string]::IsNullOrWhiteSpace($env:FORGEJO_TOKEN)) {
        $ftf = if ($env:DARNLINK_GATE_FORGEJO_TOKEN_FILE) { $env:DARNLINK_GATE_FORGEJO_TOKEN_FILE } else { Join-Path $HOME ".config/forgejo_token_ro" }
        if (Test-Path $ftf -PathType Leaf) {
          try { $env:FORGEJO_TOKEN = (Get-Content $ftf -Raw -ErrorAction Stop).Trim() } catch { }
        }
      }
      if ($forgejoPassed -and [string]::IsNullOrWhiteSpace($env:FORGEJO_TOKEN)) {
        Write-Warning "darnlink-gate: forgejo_web is declared but there is no FORGEJO_TOKEN - links to a"
        Write-Warning "  private Forgejo repo will come back web_unverifiable (COULD NOT LOOK), not verified."
      }
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
      # Only added when declared: an empty `--default-branch ""` would look like an answer.
      if ($defaultBranch) { $webArgs += @('--default-branch', $defaultBranch) }
      & uvx --from $ref darnlink web-check . --online @webArgs
      $rc = $LASTEXITCODE
      # EXIT 1 IS A USAGE ERROR, NOT A VERDICT ABOUT THE REPO, and feature 016 makes it reachable from
      # CONFIGURATION: own_web_max without own_web, an empty owner name, or own_web_from_origin in a
      # tree with no GitHub `origin`. Reporting it as a red gate would send someone hunting for broken
      # links that do not exist. Say what is wrong and drop the axis for this run.
      # Only when THIS RUN passed an own_* flag: uvx exits 1 on its own failures and an uncaught
      # Python exception exits 1 too, so an unconditional swallow would turn those green for a repo
      # that never adopted 016 — a worse guarantee than before this key existed. And it respects
      # fail_closed: in CI an axis that could not run is not a pass.
      if ($rc -eq 1 -and ($ownPassed -or $forgejoPassed)) {
        Write-Warning "darnlink-gate: web-check rejected its own arguments (exit 1) - most likely a CONFIG"
        Write-Warning "  error rather than a finding about this repository. Check own_web /"
        Write-Warning "  own_web_from_origin / own_web_max / forgejo_web in darnlink-gate.json. The web axis"
        Write-Warning "  did NOT run."
        if ($failClosed) {
          Write-Warning "  fail_closed is on: an axis that could not run is not a pass. -> 4"
          $rc = 4
        } else { $rc = 0 }
      }
      # NOT `exit` here — that was this recipe's copy of a bug the bash recipe fixed: it left before
      # the create-readme and dangling axes below, so with `web` on they never ran and the gate went
      # green on a config that said they were on. Remember the verdict and fall through; the exit
      # happens once, at the end, with the worst verdict.
      $rcIsFinal = $true
    }
  } else {
    & uvx --from $ref darnlink check . @dlArgs @args   # `darnlink check` → 0/2/3 (mode=check|repair)
    $rc = $LASTEXITCODE
  }
  # rc>3 (e.g. network) -> fail open. A final verdict (the web pass) is immune up to 4, its contract;
  # above that the tool could not run, whatever the pass.
  if ($rc -gt 4 -or (-not $rcIsFinal -and $rc -gt 3)) { Invoke-Bail "darnlink unreachable (rc=$rc)" }
  # mode=repair gates on integrity only: a strict-only failure (3) is clean. (Set, not exit, so the
  # independent axes below still run.)
  if ($mode -ceq 'repair' -and $rc -eq 3) { $rc = 0 }
  # create-readme axis: any mode (and mode=max WITH create_readme_excludes); skipped when folded above.
  if ($createReadme -and -not $foldedCR) {
    $cr = Get-CreateReadmeOffenders
    if ('ERR' -ceq $cr) {
      # Never turn an ALREADY-red gate green: keep a failing core verdict.
      if ($rc -ne 0) {
        [Console]::Error.WriteLine("darnlink-gate: create-readme axis could not run, but the core gate is already failing (rc=$rc) - keeping it.")
        exit $rc
      }
      Invoke-Bail "create-readme pass could not run (darnlink unreachable)"
    }
    if ([int]$cr -gt 0) {
      [Console]::Error.WriteLine("darnlink-gate: $cr directory link(s) point at a folder with no README (create-readme axis; fix: 'uvx --from $ref darnlink . --create-readme --write').")
      if ($rc -eq 0) { $rc = 1 }
    }
  }
  # Dangling axis, whole-repo. `added-lines` has no meaning without a staged diff, so here it reads
  # as `warn`, as in bash.
  if ($dangling -cne 'off') {
    if (-not (Get-DanglingFindings)) {
      if ($rc -ne 0) {
        [Console]::Error.WriteLine("darnlink-gate: dangling axis could not run, but the core gate is already failing (rc=$rc) - keeping it.")
        exit $rc
      }
      Invoke-Bail "dangling pass could not run (darnlink unreachable)"
    }
    $dlN = $script:dlFindings.Count
    foreach ($f in $script:dlFindings) { [Console]::Error.WriteLine("  [dangling] $($f.file): $($f.detail)") }
    # The budget verdict runs even at dlN=0: a ratchet whose reminder disappears on success is not one.
    if ($dlN -gt 0 -or ($dangling -ceq 'repo' -and $danglingMaxN -gt 0)) {
      if ($dangling -ceq 'repo') {
        if ($dlN -gt $danglingMaxN) {
          if ($danglingMaxN -gt 0) {
            [Console]::Error.WriteLine("darnlink-gate: $dlN link(s) point at a path that does not exist - over the budget of $danglingMax (dangling axis).")
          } else {
            [Console]::Error.WriteLine("darnlink-gate: $dlN link(s) point at a path that does not exist (dangling axis).")
          }
          if ($rc -eq 0) { $rc = 1 }
        } elseif ($dlN -lt $danglingMaxN) {
          if ($dlN -eq 0) {
            [Console]::Error.WriteLine("darnlink-gate: no dangling links left - drop dangling_max (still $danglingMax) so the wall is a wall again.")
          } else {
            [Console]::Error.WriteLine("darnlink-gate: $dlN dangling link(s), under the budget of $danglingMax - lower dangling_max to $dlN to keep the ratchet.")
          }
        } else {
          [Console]::Error.WriteLine("darnlink-gate: $dlN dangling link(s) - exactly at the budget (dangling_max=$danglingMax).")
        }
      } else {
        [Console]::Error.WriteLine("darnlink-gate: $dlN dangling link(s) - informational (dangling=$dangling; does not fail the gate).")
      }
    }
  }
  exit $rc
}

# ---- staged scope (Option B): darnlink judges the whole tree; WE filter findings to staged files ----
# NOTE mode=max here behaves as strict (level 2), by design: the create-frontmatter axis needs
# whole-tree reasoning, and per the wall architecture the staged pre-commit stays fast — max is
# enforced at the whole-repo wall (pre-push / CI). See docs/elevating-your-link-gate.md §7.
$staged = @(git diff --cached --name-only --diff-filter=ACMR -- '*.md' 2>$null)
if (-not $staged) { Write-Output "darnlink-gate (staged): no staged .md - nothing to judge."; exit 0 }

$json = (& uvx --from $ref darnlink check . --json @dlArgs 2>$null | Out-String)
$rc = $LASTEXITCODE
if ($rc -gt 3 -or -not ([string]$json).Trim()) { Invoke-Bail "(staged) darnlink unreachable (rc=$rc)" }

$data = $json | ConvertFrom-Json
$stagedSet = [System.Collections.Generic.HashSet[string]]::new()
foreach ($p in $staged) { [void]$stagedSet.Add(([IO.Path]::GetFullPath((Join-Path $root $p)))) }
function Hits($axis) { @($data.$axis.findings | Where-Object { $null -ne $_ -and $stagedSet.Contains(([IO.Path]::GetFullPath($_.file))) }) }

# The lines THIS COMMIT ADDS, per staged file (full path -> set of line numbers), from
# `git diff --cached -U0`: every `+` line in a hunk header's range is new. `+N` with no count is one
# line; `+N,0` is a pure deletion. Same parse as the bash recipe's sed.
function Get-AddedLines($paths) {
  $ErrorActionPreference = 'Continue'
  $added = @{}
  foreach ($p in $paths) {
    if (-not $p) { continue }
    $key = [IO.Path]::GetFullPath((Join-Path $root $p))
    foreach ($ln in @(git diff --cached -U0 -- $p 2>$null)) {
      if ($ln -cmatch '^@@ -\S* \+([0-9]+)(,([0-9]+))? @@') {
        $start = [int]$Matches[1]
        $count = if ($Matches.ContainsKey(3)) { [int]$Matches[3] } else { 1 }
        if (-not $added.ContainsKey($key)) { $added[$key] = [System.Collections.Generic.HashSet[int]]::new() }
        for ($i = $start; $i -lt $start + $count; $i++) { [void]$added[$key].Add($i) }
      }
    }
  }
  return $added
}

$integ  = @(Hits 'integrity')
# @( ) around the whole `if`: its output is unrolled, and a lone PSCustomObject has no .Count in 5.1.
$strict = @(if ($mode -ceq 'repair') { } else { Hits 'strict' })   # mode=repair gates on integrity only
# --- dangling axis (015): `added-lines` judges only the lines the commit ADDS ---
$dang = @()
if ($dangling -cne 'off') {
  $found = @(Hits 'dangling')
  if ($dangling -ceq 'added-lines') {
    $added = Get-AddedLines $staged
    $dang = @($found | Where-Object {
      $k = [IO.Path]::GetFullPath($_.file)
      $null -ne $_.line -and $added.ContainsKey($k) -and $added[$k].Contains([int]$_.line)
    })
  } else { $dang = $found }
}
foreach ($f in $integ)  { Write-Output "  [integrity/$($f.kind)] $($f.file): $($f.detail)" }
foreach ($f in $strict) { Write-Output "  [strict/$($f.kind)] $($f.file): $($f.detail)" }
foreach ($f in $dang)   { Write-Output "  [dangling] $($f.file): $($f.detail)" }
if ($integ.Count -gt 0)  { Write-Output "darnlink-gate (staged): integrity failure in a file you're committing."; exit 2 }
if ($strict.Count -gt 0) { Write-Output "darnlink-gate (staged): un-anchored plain link in a file you're committing (anchor it: uvx --from $ref darnlink . --robustify --write)."; exit 3 }
if ($dang.Count -gt 0 -and $dangling -cne 'warn') {
  Write-Output "darnlink-gate (staged): $($dang.Count) link(s) you are adding point at a path that does not exist. Fix the path, or drop the link if the target is gone."
  exit 1
}
if ($dang.Count -gt 0) { Write-Output "darnlink-gate (staged): $($dang.Count) dangling link(s) - informational (dangling=warn)." }
Write-Output "darnlink-gate (staged): clean."; exit 0
