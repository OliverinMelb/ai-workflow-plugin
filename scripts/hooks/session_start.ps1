# SessionStart hook (plugin engine): inject memory pointers into new sessions.
# stdout is appended to the session context. Keep this SHORT — pointers, not content.
# Two tiers: project memory (from <project>/workflow/config.json) + global
# memory (~/.claude/workflow-memory: machine facts and cross-project lessons).
#
# Generic engine: project root resolves from the session cwd via git, and the
# hook exits silently in projects that have no workflow/config.json (the
# plugin is installed user-wide; only workflow-enabled projects get output).

$ErrorActionPreference = 'SilentlyContinue'

$repoRoot = git rev-parse --show-toplevel 2>$null
if (-not $repoRoot) { exit 0 }
$repoRoot = $repoRoot -replace '/', '\'

$configPath = Join-Path $repoRoot 'workflow\config.json'
if (-not (Test-Path $configPath)) { exit 0 }
$config = Get-Content $configPath -Raw | ConvertFrom-Json

Write-Output "## $($config.project_name) project memory (auto-loaded)"
foreach ($pointer in $config.memory.pointers) {
  Write-Output "- $pointer"
}

# Global memory tier: facts that hold on this machine across ALL projects.
$globalDir = $config.memory.global_memory_dir -replace '^~', $HOME
if ($globalDir -and (Test-Path $globalDir)) {
  $globalFiles = (Get-ChildItem $globalDir -Filter '*.md' | ForEach-Object { $_.BaseName }) -join ', '
  Write-Output "- Global workflow memory (machine facts, cross-project lessons): $globalDir ($globalFiles)"
}

$registryPath = Join-Path $repoRoot 'workflow\state\worktree-registry.json'
if (Test-Path $registryPath) {
  $registry = Get-Content $registryPath -Raw | ConvertFrom-Json
  $active = @()
  foreach ($t in $registry.tasks) {
    foreach ($s in $t.subtasks) {
      if (Test-Path $s.worktree_path) {
        $active += "  - $($t.task_id) / $($s.subtask_id) [$($s.workflow)] -> $($s.worktree_path)"
      }
    }
  }
  if ($active.Count -gt 0) {
    Write-Output "- Active subtask worktrees:"
    $active | Write-Output
  }
}

exit 0
