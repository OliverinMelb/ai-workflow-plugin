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

& $python (Join-Path $PSScriptRoot 'register_worktree.py') $TaskId $SubtaskId $branchName $worktreePath $Workflow

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
