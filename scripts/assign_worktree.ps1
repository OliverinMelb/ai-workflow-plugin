param(
  [Parameter(Mandatory = $true)]
  [string]$TaskId,

  [Parameter(Mandatory = $true)]
  [string]$SubtaskId,

  [Parameter(Mandatory = $true)]
  [string]$Workflow,

  [string]$BranchPrefix = 'subtask',

  [switch]$NoCreate
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')

$repoRoot = Get-MainRoot
$config = Get-WorkflowConfig $repoRoot
$python = Resolve-ProjectPython $config $repoRoot

$subtaskFile = Join-Path $repoRoot "workflow\tasks\$TaskId\subtasks\$SubtaskId.md"
if (-not (Test-Path $subtaskFile)) {
  throw "Subtask file not found: $subtaskFile"
}

$branchName = "$BranchPrefix/$SubtaskId"
$worktreePath = Join-Path (Split-Path $repoRoot -Parent) "wt-$SubtaskId"

if (-not $NoCreate) {
  git -C $repoRoot worktree add $worktreePath -b $branchName | Out-Null
}

# base_sha = the commit this subtask branched from; every later diff, checker
# and review compares base_sha...candidate_sha instead of guessing a baseline.
$baseSha = ''
if (Test-Path $worktreePath) {
  if ($NoCreate) {
    $mainHead = (git -C $repoRoot rev-parse HEAD).Trim()
    $baseSha = ("$(git -C $worktreePath merge-base HEAD $mainHead 2>$null)").Trim()
  }
  if (-not $baseSha) {
    $baseSha = (git -C $worktreePath rev-parse HEAD).Trim()
  }
}

& $python (Join-Path $PSScriptRoot 'register_worktree.py') $TaskId $SubtaskId $branchName $worktreePath $Workflow $baseSha

# Provision the worktree so it can run all checks with zero installs
# (node component junctions to the main checkout; python components use the
# shared main venv). Idempotent, so safe under -NoCreate too.
if (Test-Path $worktreePath) {
  & (Join-Path $PSScriptRoot 'bootstrap.ps1') -TargetRoot $worktreePath
}

Write-Output "task_id=$TaskId"
Write-Output "subtask_id=$SubtaskId"
Write-Output "branch=$branchName"
Write-Output "worktree=$worktreePath"
Write-Output "workflow=$Workflow"
Write-Output "base_sha=$baseSha"
