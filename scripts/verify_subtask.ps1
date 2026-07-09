# Independent re-verification of a subtask (engine).
# Never trust the subagent's self-reported check results: this script re-runs
# the verification matrix for the subtask's workflow class inside its worktree
# and writes an evidence file consumed by assemble_reviewer_packet.ps1.
# Matrix comes from the project's workflow/config.json.

param(
  [Parameter(Mandatory = $true)]
  [string]$TaskId,

  [Parameter(Mandatory = $true)]
  [string]$SubtaskId
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')

$repoRoot = Get-MainRoot
$config = Get-WorkflowConfig $repoRoot
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
if (-not $entry) { throw "Subtask not found in registry: $TaskId / $SubtaskId" }

$worktree = $entry.worktree_path -replace '/', '\'
if (-not (Test-Path $worktree)) { throw "Worktree path does not exist: $worktree" }

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
    $checks += @{ name = $c.name; dir = $c.dir; cmd = $cmd; args = @($c.args) }
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

$summaryDir = Join-Path $repoRoot "workflow\tasks\$TaskId\subtask-summaries"
if (-not (Test-Path $summaryDir)) { New-Item -ItemType Directory -Force $summaryDir | Out-Null }
$evidencePath = Join-Path $summaryDir "$SubtaskId.verify.md"

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$lines = @()
$lines += "# Independent Verification: $SubtaskId"
$lines += ""
$lines += "- task: $TaskId"
$lines += "- workflow: $($entry.workflow)"
$lines += "- worktree: $worktree"
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
if (-not $allPassed) { exit 1 }
