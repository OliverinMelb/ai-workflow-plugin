# Independent re-verification of a subtask (engine).
# Never trust the subagent's self-reported check results: this script re-runs
# the verification matrix for the subtask's workflow class inside its worktree
# and writes an evidence file consumed by assemble_reviewer_packet.ps1.
# Matrix comes from the project's workflow/config.json.

param(
  [Parameter(Mandatory = $true)]
  [string]$TaskId,

  [Parameter(Mandatory = $true)]
  [string]$SubtaskId,

  # Small-tier tasks work directly on a branch without an assigned worktree /
  # registry entry. Pass -WorktreePath (the tree to verify, e.g. the main
  # checkout) together with -Workflow to verify without a registry lookup.
  [string]$WorktreePath,

  [string]$Workflow,

  # Direct-form runs have no registry entry; pass the base_sha recorded in the
  # task brief so checkers can classify the committed range.
  [string]$BaseSha
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')

$repoRoot = Get-MainRoot
$config = Get-WorkflowConfig $repoRoot

if ($WorktreePath) {
  if (-not $Workflow) { throw "-WorktreePath requires -Workflow <class>" }
  $entry = [pscustomobject]@{ worktree_path = $WorktreePath; workflow = $Workflow }
} else {
  $registryPath = Join-Path $repoRoot 'workflow\state\worktree-registry.json'
  $registry = Get-Content $registryPath -Raw | ConvertFrom-Json

  $entry = $null
  foreach ($t in $registry.tasks) {
    if ($t.task_id -eq $TaskId) {
      foreach ($s in $t.subtasks) {
        if ($s.subtask_id -eq $SubtaskId) { $entry = $s }
      }
    }
  }
  if (-not $entry) { throw "Subtask not found in registry: $TaskId / $SubtaskId (small-tier direct-branch work: pass -WorktreePath and -Workflow instead)" }
}

$worktree = $entry.worktree_path -replace '/', '\'
if (-not (Test-Path $worktree)) { throw "Worktree path does not exist: $worktree" }

# Bind the evidence to the exact candidate version: SHA, dirty fingerprint and
# config hash. A PASS is only valid for this precise state.
$candidateSha = (git -C $worktree rev-parse HEAD).Trim()
$resolvedBaseSha = if ($BaseSha) { $BaseSha }
  elseif ($entry.PSObject.Properties['base_sha'] -and $entry.base_sha) { "$($entry.base_sha)" }
  else { '' }
$configSha = (Get-FileHash (Join-Path $repoRoot 'workflow\config.json') -Algorithm SHA256).Hash.Substring(0, 12).ToLowerInvariant()

# Checkers (e.g. contract touchpoints) read these to classify the committed
# range base_sha...candidate_sha, not just the working tree.
$env:WORKFLOW_BASE_SHA = $resolvedBaseSha
$env:WORKFLOW_CANDIDATE_SHA = $candidateSha

$python = Resolve-ProjectPython $config $repoRoot

# workflow_classes maps a class to check-group names; checks defines each
# group. cmd "python" is a convention resolved to the interpreter above.
$groupNames = $config.workflow_classes.($entry.workflow)
if (-not $groupNames) { throw "Unknown workflow class: $($entry.workflow) (not in config.workflow_classes)" }

$checks = @()
foreach ($group in $groupNames) {
  $groupChecks = $config.checks.$group
  if (-not $groupChecks) { throw "Check group '$group' not defined in config.checks" }
  foreach ($c in $groupChecks) {
    $cmd = if ($c.cmd -eq 'python') { $python } else { $c.cmd }
    # "{engine}/foo.py" in args resolves to the plugin's scripts dir, so
    # project configs never hardcode where the engine lives.
    $resolvedArgs = @($c.args | ForEach-Object { $_ -replace '^\{engine\}', ($PSScriptRoot -replace '\\', '/') })
    $checks += @{ name = $c.name; dir = $c.dir; cmd = $cmd; args = $resolvedArgs }
  }
}

$results = @()
$allPassed = $true
foreach ($check in $checks) {
  $runDir = if ($check.dir) { Join-Path $worktree $check.dir } else { $worktree }
  Write-Output "[verify] $($check.name) in $runDir"
  Push-Location $runDir
  try {
    # PS 5.1: native stderr under 2>&1 becomes ErrorRecords; with EAP=Stop that
    # kills the script on harmless progress output (vite/npm write to stderr).
    $ErrorActionPreference = 'Continue'
    $output = (& $check.cmd @($check.args) 2>&1 | ForEach-Object { "$_" }) -join "`r`n"
    $code = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = 'Stop'
    Pop-Location
  }
  $status = if ($code -eq 0) { 'PASS' } else { 'FAIL' }
  if ($code -ne 0) { $allPassed = $false }
  $results += [pscustomobject]@{ name = $check.name; status = $status; exit = $code; output = $output }
}

$env:WORKFLOW_BASE_SHA = $null
$env:WORKFLOW_CANDIDATE_SHA = $null

# Evidence is only sound if it still describes the tree we just checked.
$headNow = (git -C $worktree rev-parse HEAD).Trim()
if ($headNow -ne $candidateSha) {
  throw "HEAD moved during verification ($candidateSha -> $headNow); evidence would be unsound. Re-run."
}

# Dirty fingerprint at evidence time. subtask-summary.md (the deliberately
# uncommitted summary collected below) is excluded by design.
$dirtyEntries = @(git -C $worktree status --porcelain | Where-Object { $_ -and ($_ -notmatch 'subtask-summary\.md$') })
$dirty = $dirtyEntries.Count -gt 0

$summaryDir = Join-Path $repoRoot "workflow\tasks\$TaskId\subtask-summaries"
if (-not (Test-Path $summaryDir)) { New-Item -ItemType Directory -Force $summaryDir | Out-Null }
$evidencePath = Join-Path $summaryDir "$SubtaskId.verify.md"

# Engine-side collection: the implementer writes subtask-summary.md at its
# worktree root (it never writes across the worktree boundary); verification
# collects it into the task packet.
$wtSummary = Join-Path $worktree 'subtask-summary.md'
$collectedSummary = Join-Path $summaryDir "$SubtaskId.md"
$summaryCollected = $false
if (Test-Path $wtSummary) {
  Copy-Item $wtSummary $collectedSummary -Force
  $summaryCollected = $true
}

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$lines = @()
$lines += "# Independent Verification: $SubtaskId"
$lines += ""
$lines += "- task: $TaskId"
$lines += "- workflow: $($entry.workflow)"
$lines += "- worktree: $worktree"
$lines += "- base_sha: $(if ($resolvedBaseSha) { $resolvedBaseSha } else { '(not recorded)' })"
$lines += "- candidate_sha: $candidateSha"
$lines += "- dirty: $(if ($dirty) { "true ($($dirtyEntries.Count) uncommitted entries -- candidate incomplete, evidence provisional)" } else { 'false' })"
$lines += "- config_sha256: $configSha"
$lines += "- run at: $stamp (re-run by orchestrator/reviewer, NOT subagent self-report)"
$lines += "- overall: $(if ($allPassed) { 'PASS' } else { 'FAIL' })"
$lines += ""
foreach ($r in $results) {
  $lines += "## $($r.name): $($r.status) (exit $($r.exit))"
  $lines += '```'
  $lines += ($r.output.TrimEnd() -split "`r?`n" | Select-Object -Last 40)
  $lines += '```'
  $lines += ""
}
$lines -join "`r`n" | Out-File -FilePath $evidencePath -Encoding utf8

Write-Output ""
Write-Output "overall=$(if ($allPassed) { 'PASS' } else { 'FAIL' })"
Write-Output "evidence=$evidencePath"
Write-Output "candidate_sha=$candidateSha"
Write-Output "dirty=$dirty"
Write-Output "summary_collected=$(if ($summaryCollected) { $collectedSummary } else { 'NO (subtask-summary.md not found in worktree)' })"
if (-not $allPassed) { exit 1 }
