param(
  [Parameter(Mandatory = $true)]
  [string]$TaskId,

  [Parameter(Mandatory = $true)]
  [string]$SubtaskId,

  [string]$OutFile
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')

$repoRoot = Get-MainRoot
$config = Get-WorkflowConfig $repoRoot
$taskDir = Join-Path $repoRoot "workflow\tasks\$TaskId"
$subtaskSpecPath = Join-Path $taskDir "subtasks\$SubtaskId.md"
$registryPath = Join-Path $repoRoot 'workflow\state\worktree-registry.json'
$templatePath = Join-Path $repoRoot 'workflow\templates\subagent-prompt.md'
$agentsPath = Join-Path $repoRoot 'AGENTS.md'
$workflowReadmePath = Join-Path $repoRoot 'workflow\README.md'
$verificationNotesPath = Join-Path $repoRoot 'workflow\checks\verification.md'
$summaryTemplatePath = Join-Path $repoRoot 'workflow\templates\subtask-summary.md'
$briefPath = Join-Path $taskDir 'brief.md'
$specPath = Join-Path $taskDir 'spec.md'
$planPath = Join-Path $taskDir 'plan.md'
$summaryDir = Join-Path $taskDir 'subtask-summaries'
$summaryPath = Join-Path $summaryDir "$SubtaskId.md"

if (-not (Test-Path $taskDir)) {
  throw "Task not found: $TaskId"
}

if (-not (Test-Path $subtaskSpecPath)) {
  throw "Subtask spec not found: $subtaskSpecPath"
}

if (-not (Test-Path $registryPath)) {
  throw "Worktree registry not found: $registryPath"
}

if (-not (Test-Path $summaryDir)) {
  New-Item -ItemType Directory -Path $summaryDir -Force | Out-Null
}

$registry = Get-Content $registryPath -Raw | ConvertFrom-Json
$taskEntry = $registry.tasks | Where-Object { $_.task_id -eq $TaskId } | Select-Object -First 1
if (-not $taskEntry) {
  throw "Task not registered in worktree registry: $TaskId"
}

$subtaskEntry = $taskEntry.subtasks | Where-Object { $_.subtask_id -eq $SubtaskId } | Select-Object -First 1
if (-not $subtaskEntry) {
  throw "Subtask not registered in worktree registry: $TaskId / $SubtaskId"
}

$workflow = $subtaskEntry.workflow

# Optional per-class runbook; fall back to the workflow README.
$workflowReferencePath = Join-Path $repoRoot "workflow\workflows\$workflow.md"
if (-not (Test-Path $workflowReferencePath)) { $workflowReferencePath = $workflowReadmePath }

# Checks block is generated from workflow/config.json so the prompt never
# drifts from the actual verification matrix. Checks are grouped by run dir.
$groupNames = $config.workflow_classes.$workflow
if (-not $groupNames) { throw "Unknown workflow class: $workflow (not in config.workflow_classes)" }

$checksLines = @()
$lastDir = $null
foreach ($group in $groupNames) {
  foreach ($c in $config.checks.$group) {
    $dirLabel = if ($c.dir) { "``$($c.dir)``" } else { 'repo root' }
    if ($dirLabel -ne $lastDir) {
      $checksLines += "- from $dirLabel run:"
      $lastDir = $dirLabel
    }
    $checksLines += "  - ``$($c.cmd) $($c.args -join ' ')``"
  }
}
$checksBlock = [string]::Join("`r`n", $checksLines)

# spec.md / plan.md are optional since brief became the single task doc:
# emit a real pointer only when the file exists, never a dead path.
$specRef = if (Test-Path $specPath) { "``$specPath``" } else { '(not created -- brief.md is authoritative)' }
$planRef = if (Test-Path $planPath) { "``$planPath``" } else { '(not created -- see the Plan section in brief.md)' }

# -Encoding UTF8: templates are UTF-8 without BOM; PS 5.1 defaults to ANSI
# and mangles any non-ASCII character on zh locales.
$content = Get-Content $templatePath -Raw -Encoding UTF8
$replacements = @{
  '{{TASK_ID}}' = $TaskId
  '{{SUBTASK_ID}}' = $SubtaskId
  '{{WORKFLOW}}' = $workflow
  '{{REPO_ROOT}}' = $repoRoot
  '{{WORKTREE_PATH}}' = $subtaskEntry.worktree_path
  '{{BRANCH}}' = $subtaskEntry.branch
  '{{AGENTS_PATH}}' = $agentsPath
  '{{WORKFLOW_README_PATH}}' = $workflowReadmePath
  '{{SUBTASK_SPEC_PATH}}' = $subtaskSpecPath
  '{{WORKFLOW_REFERENCE_PATH}}' = $workflowReferencePath
  '{{VERIFICATION_NOTES_PATH}}' = $verificationNotesPath
  '{{PARENT_BRIEF_PATH}}' = $briefPath
  '{{PARENT_SPEC_REF}}' = $specRef
  '{{TASK_PLAN_REF}}' = $planRef
  # legacy placeholders (older scaffolded project templates):
  '{{PARENT_SPEC_PATH}}' = $specPath
  '{{TASK_PLAN_PATH}}' = $planPath
  '{{SUBTASK_SUMMARY_PATH}}' = $summaryPath
  '{{SUBTASK_SUMMARY_TEMPLATE_PATH}}' = $summaryTemplatePath
  '{{CHECKS_BLOCK}}' = $checksBlock
}

foreach ($key in $replacements.Keys) {
  $content = $content.Replace($key, [string]$replacements[$key])
}

if ($OutFile) {
  $outPath = if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path $taskDir $OutFile }
  $outDir = Split-Path -Parent $outPath
  if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
  }
  Set-Content -Path $outPath -Value $content -Encoding UTF8
  Write-Output "prompt_file=$outPath"
}
else {
  Write-Output $content
}

Write-Output "task_id=$TaskId"
Write-Output "subtask_id=$SubtaskId"
Write-Output "workflow=$workflow"
Write-Output "worktree=$($subtaskEntry.worktree_path)"
Write-Output "branch=$($subtaskEntry.branch)"
Write-Output "summary_path=$summaryPath"
