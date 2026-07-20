param(
  [Parameter(Mandatory = $true)]
  [string]$TaskId,

  [string]$OutFile,

  # Escape hatch for the staleness gate below; the packet still labels the
  # evidence as stale. Only for human-approved exceptions.
  [switch]$AllowStale
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')

$repoRoot = Get-MainRoot
$taskDir = Join-Path $repoRoot "workflow\tasks\$TaskId"
$briefPath = Join-Path $taskDir 'brief.md'
$specPath = Join-Path $taskDir 'spec.md'
$reviewerTemplatePath = Join-Path $repoRoot 'workflow\templates\reviewer-packet.md'
$registryPath = Join-Path $repoRoot 'workflow\state\worktree-registry.json'
$summaryDir = Join-Path $taskDir 'subtask-summaries'
$reportsDir = Join-Path $repoRoot 'workflow\reports'

if (-not (Test-Path $taskDir)) {
  throw "Task not found: $TaskId"
}

if (-not (Test-Path $registryPath)) {
  throw "Worktree registry not found: $registryPath"
}

$registry = Get-Content $registryPath -Raw | ConvertFrom-Json
$taskEntry = $registry.tasks | Where-Object { $_.task_id -eq $TaskId } | Select-Object -First 1
$subtasks = @()
if ($taskEntry) {
  $subtasks = @($taskEntry.subtasks)
}

# Pointer, not inlined content: the reviewer agent has Read and pulls the
# brief itself. Inlining duplicated multi-KB of text into every packet.
$requirementSummary = ''
if (Test-Path $briefPath) {
  $requirementSummary = "Read the task brief (goal, acceptance criteria, stop conditions): ``$briefPath``"
}
elseif (Test-Path $specPath) {
  $requirementSummary = "Read the task spec (no brief found): ``$specPath``"
}

$subtaskLines = New-Object System.Collections.Generic.List[string]
$changedFileLines = New-Object System.Collections.Generic.List[string]
$checkerLines = New-Object System.Collections.Generic.List[string]

foreach ($subtask in $subtasks) {
  $summaryPath = Join-Path $summaryDir ($subtask.subtask_id + '.md')
  $verifyPath = Join-Path $summaryDir ($subtask.subtask_id + '.verify.md')

  $baseSha = ''
  if ($subtask.PSObject.Properties['base_sha'] -and $subtask.base_sha) { $baseSha = "$($subtask.base_sha)" }

  $headSha = ''
  if (Test-Path $subtask.worktree_path) {
    $headSha = ("$(git -C $subtask.worktree_path rev-parse HEAD 2>$null)").Trim()
  }

  # Staleness gate: verify evidence must be bound to the exact commit under
  # review. A mismatch means code changed after verification -- the PASS no
  # longer describes this candidate.
  $verifiedSha = ''
  if (Test-Path $verifyPath) {
    $shaLine = (Get-Content $verifyPath | Where-Object { $_ -match '^- candidate_sha: ' } | Select-Object -First 1)
    if ($shaLine -and $shaLine -match '^- candidate_sha: ([0-9a-f]+)') { $verifiedSha = $Matches[1] }
  }
  if ($headSha -and $verifiedSha -and ($verifiedSha -ne $headSha) -and -not $AllowStale) {
    throw "Stale verification evidence for $($subtask.subtask_id): verified $verifiedSha but worktree HEAD is $headSha. Re-run verify_subtask.ps1 first (or pass -AllowStale to override, packet will label it stale)."
  }

  $evidenceLabel = if (-not (Test-Path $verifyPath)) { 'MISSING -- run verify_subtask.ps1' }
    elseif (-not $verifiedSha) { "$verifyPath (NOT SHA-bound -- re-run verify)" }
    elseif ($headSha -and ($verifiedSha -ne $headSha)) { "$verifyPath (STALE: bound to $verifiedSha, HEAD is $headSha)" }
    else { "$verifyPath (bound to $verifiedSha)" }

  $subtaskLines.Add("- name: $($subtask.subtask_id)")
  $subtaskLines.Add("- worktree: $($subtask.worktree_path)")
  $subtaskLines.Add("- branch: $($subtask.branch)")
  $subtaskLines.Add("- base_sha: $(if ($baseSha) { $baseSha } else { '(not recorded)' })")
  $subtaskLines.Add("- candidate_sha: $(if ($headSha) { $headSha } else { '(worktree missing)' })")
  $subtaskLines.Add("- verify evidence: $evidenceLabel")
  $subtaskLines.Add("- summary: $summaryPath")

  if (Test-Path $subtask.worktree_path) {
    # Canonical change set = committed range base_sha...HEAD. Staged/unstaged
    # leftovers are reported separately: they are NOT part of the candidate.
    if ($baseSha) {
      $committed = git -C $subtask.worktree_path diff --name-only "$baseSha...HEAD"
      if ($LASTEXITCODE -eq 0 -and $committed) {
        foreach ($file in $committed) {
          $changedFileLines.Add("- $($subtask.subtask_id): $file")
        }
      }
      else {
        $changedFileLines.Add("- $($subtask.subtask_id): no committed changes in $baseSha...HEAD")
      }
    }
    else {
      $changedFileLines.Add("- $($subtask.subtask_id): base_sha not recorded (pre-upgrade entry); falling back to working-tree diff vs HEAD")
      $fallback = git -C $subtask.worktree_path diff --name-only HEAD
      if ($LASTEXITCODE -eq 0 -and $fallback) {
        foreach ($file in $fallback) {
          $changedFileLines.Add("- $($subtask.subtask_id): $file (working tree)")
        }
      }
    }
    $staged = @(git -C $subtask.worktree_path diff --cached --name-only | Where-Object { $_ })
    foreach ($file in $staged) {
      $changedFileLines.Add("- $($subtask.subtask_id): WARNING uncommitted (staged): $file")
    }
    $unstaged = @(git -C $subtask.worktree_path diff --name-only | Where-Object { $_ -and $_ -notmatch 'subtask-summary\.md$' })
    foreach ($file in $unstaged) {
      $changedFileLines.Add("- $($subtask.subtask_id): WARNING uncommitted (unstaged): $file")
    }
  }
  else {
    $changedFileLines.Add("- $($subtask.subtask_id): worktree path not found")
  }

  if (Test-Path $summaryPath) {
    $statusLine = (Get-Content $summaryPath | Where-Object { $_ -match '^\- status:' } | Select-Object -First 1)
    if ($statusLine) {
      $checkerLines.Add("- $($subtask.subtask_id): $statusLine")
    }
    else {
      $checkerLines.Add("- $($subtask.subtask_id): summary present, status line missing")
    }
  }
  else {
    $checkerLines.Add("- $($subtask.subtask_id): summary missing")
  }
}

$reportFiles = @()
if (Test-Path $reportsDir) {
  $reportFiles = @(Get-ChildItem $reportsDir -File | Sort-Object LastWriteTime -Descending | Select-Object -First 5)
}
foreach ($report in $reportFiles) {
  $checkerLines.Add("- report: $($report.FullName)")
}

$template = Get-Content $reviewerTemplatePath -Raw -Encoding UTF8
$template = $template -replace '(?s)## Parent Task\s*.*?(?=## Requirement Summary)', "## Parent Task`r`n$TaskId`r`n`r`n"
$template = $template -replace '(?s)## Requirement Summary\s*.*?(?=## Acceptance Criteria)', "## Requirement Summary`r`n$requirementSummary`r`n`r`n"
$template = $template -replace '(?s)## Subtasks\s*.*?(?=## Changed Files By Subtask)', "## Subtasks`r`n$([string]::Join("`r`n", $subtaskLines))`r`n`r`n"
$template = $template -replace '(?s)## Changed Files By Subtask\s*.*?(?=## Checker Results)', "## Changed Files By Subtask`r`n$([string]::Join("`r`n", $changedFileLines))`r`n`r`n"
$template = $template -replace '(?s)## Checker Results\s*.*?(?=## Reviewer Decision)', "## Checker Results`r`n$([string]::Join("`r`n", $checkerLines))`r`n`r`n"

$outPath = if ($OutFile) {
  if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path $taskDir $OutFile }
}
else {
  Join-Path $taskDir 'reviewer-packet.md'
}

Set-Content -Path $outPath -Value $template -Encoding UTF8

Write-Output "task_id=$TaskId"
Write-Output "reviewer_packet=$outPath"
Write-Output "subtask_count=$($subtasks.Count)"
