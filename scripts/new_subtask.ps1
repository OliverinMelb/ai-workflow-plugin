param(
  [Parameter(Mandatory = $true)]
  [string]$TaskId,

  [Parameter(Mandatory = $true)]
  [string]$Title,

  [string]$Workflow = 'contract-change'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')

$repoRoot = Get-MainRoot
$templatesRoot = Join-Path $repoRoot 'workflow\templates'
$taskDir = Join-Path $repoRoot "workflow\tasks\$TaskId"
$subtasksDir = Join-Path $taskDir 'subtasks'

if (-not (Test-Path $taskDir)) {
  throw "Task not found: $TaskId"
}

New-Item -ItemType Directory -Path $subtasksDir -Force | Out-Null

$slug = $Title.ToLowerInvariant()
$slug = $slug -replace '[^a-z0-9]+','-'
$slug = $slug.Trim('-')
if ([string]::IsNullOrWhiteSpace($slug)) {
  throw 'Unable to derive subtask slug from Title.'
}

$subtaskPath = Join-Path $subtasksDir "$slug.md"
if (Test-Path $subtaskPath) {
  throw "Subtask already exists: $subtaskPath"
}

Copy-Item (Join-Path $templatesRoot 'subtask-spec.md') $subtaskPath
Add-Content $subtaskPath "`n## Parent Task`n$TaskId`n"
Add-Content $subtaskPath "`n## Subtask Title`n$Title`n"
Add-Content $subtaskPath "`n## Recommended Workflow`n$Workflow`n"

Write-Output "task_id=$TaskId"
Write-Output "subtask_id=$slug"
Write-Output "subtask_file=$subtaskPath"
Write-Output "workflow=$Workflow"
