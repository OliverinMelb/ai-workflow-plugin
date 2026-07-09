param(
  [Parameter(Mandatory = $true)]
  [string]$Title,

  [string]$Workflow = 'contract-change',

  [string]$BranchPrefix = 'task',

  [string[]]$Subtasks = @(),

  [switch]$NoWorktree
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')

$repoRoot = Get-MainRoot
$tasksRoot = Join-Path $repoRoot 'workflow\tasks'
$templatesRoot = Join-Path $repoRoot 'workflow\templates'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'

$slug = $Title.ToLowerInvariant()
$slug = $slug -replace '[^a-z0-9]+','-'
$slug = $slug.Trim('-')
if ([string]::IsNullOrWhiteSpace($slug)) {
  throw 'Unable to derive slug from Title.'
}

$taskId = "$timestamp-$slug"
$taskDir = Join-Path $tasksRoot $taskId
$subtasksDir = Join-Path $taskDir 'subtasks'
$subtaskSummariesDir = Join-Path $taskDir 'subtask-summaries'
New-Item -ItemType Directory -Path $taskDir -Force | Out-Null
New-Item -ItemType Directory -Path $subtasksDir -Force | Out-Null
New-Item -ItemType Directory -Path $subtaskSummariesDir -Force | Out-Null

Copy-Item (Join-Path $templatesRoot 'task-brief.md') (Join-Path $taskDir 'brief.md')
Copy-Item (Join-Path $templatesRoot 'task-spec.md') (Join-Path $taskDir 'spec.md')
Copy-Item (Join-Path $templatesRoot 'task-plan.md') (Join-Path $taskDir 'plan.md')
Copy-Item (Join-Path $templatesRoot 'task-backlog.md') (Join-Path $taskDir 'backlog.md')
Copy-Item (Join-Path $templatesRoot 'task-summary.md') (Join-Path $taskDir 'summary.md')
Copy-Item (Join-Path $templatesRoot 'reviewer-packet.md') (Join-Path $taskDir 'reviewer-packet.md')

$branchName = "$BranchPrefix/$slug"
$worktreePath = Join-Path (Split-Path $repoRoot -Parent) "wt-$slug"

if (-not $NoWorktree) {
  git -C $repoRoot worktree add $worktreePath -b $branchName | Out-Null
}

# Optional per-class runbook; projects may or may not ship one.
$workflowFile = "workflow/workflows/$Workflow.md"
if (-not (Test-Path (Join-Path $repoRoot ($workflowFile -replace '/', '\')))) {
  $workflowFile = '(no per-class runbook in this project)'
}

$briefPath = Join-Path $taskDir 'brief.md'
$specPath = Join-Path $taskDir 'spec.md'
$planPath = Join-Path $taskDir 'plan.md'
$backlogPath = Join-Path $taskDir 'backlog.md'
$summaryPath = Join-Path $taskDir 'summary.md'
$reviewerPacketPath = Join-Path $taskDir 'reviewer-packet.md'

Add-Content $briefPath "`n## Task`n$Title`n"
Add-Content $briefPath "`n## Workflow`n$Workflow`n"
Add-Content $specPath "`n## Task`n$Title`n"
Add-Content $planPath "`n## Workflow Reference`n$workflowFile`n"
Add-Content $planPath "`n## Worktree`n- branch: $branchName`n- path: $worktreePath`n"
Add-Content $backlogPath "`n## Task`n$Title`n"
Add-Content $summaryPath "`n## Task`n$Title`n"
Add-Content $reviewerPacketPath "`n## Parent Task`n$Title`n"

$createdSubtasks = @()
foreach ($subtask in $Subtasks) {
  $subSlug = $subtask.ToLowerInvariant()
  $subSlug = $subSlug -replace '[^a-z0-9]+','-'
  $subSlug = $subSlug.Trim('-')
  if ([string]::IsNullOrWhiteSpace($subSlug)) {
    continue
  }

  $subtaskPath = Join-Path $subtasksDir "$subSlug.md"
  Copy-Item (Join-Path $templatesRoot 'subtask-spec.md') $subtaskPath
  Add-Content $subtaskPath "`n## Parent Task`n$taskId`n"
  Add-Content $subtaskPath "`n## Subtask Title`n$subtask`n"
  $createdSubtasks += $subSlug
}

Write-Output "task_id=$taskId"
Write-Output "task_dir=$taskDir"
Write-Output "branch=$branchName"
if (-not $NoWorktree) {
  Write-Output "worktree=$worktreePath"
}
Write-Output "workflow=$workflowFile"
Write-Output "subtasks_dir=$subtasksDir"
Write-Output "subtask_summaries_dir=$subtaskSummariesDir"
if ($createdSubtasks.Count -gt 0) {
  Write-Output "subtasks=$($createdSubtasks -join ',')"
}
