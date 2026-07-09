# Shared helpers for ai-workflow engine scripts. Dot-source from siblings:
#   . (Join-Path $PSScriptRoot '_lib.ps1')
# Scripts live in the plugin, so the project root can NEVER be derived from
# $PSScriptRoot — always resolve from the current working directory via git.

function Get-MainRoot {
  # Main checkout root (first entry of worktree list), even when cwd is
  # inside a linked worktree or a subdirectory. Task packets, registry and
  # shared deps all live in the main checkout.
  $porcelain = git worktree list --porcelain 2>$null
  foreach ($line in $porcelain) {
    if ($line -match '^worktree (.+)$') { return ($Matches[1] -replace '/', '\') }
  }
  throw "Not inside a git repository. Run from the project you are orchestrating."
}

function Get-WorkflowConfig {
  param([string]$RepoRoot)
  $configPath = Join-Path $RepoRoot 'workflow\config.json'
  if (-not (Test-Path $configPath)) {
    throw "workflow/config.json not found in $RepoRoot. Run the workflow-init skill first."
  }
  return Get-Content $configPath -Raw | ConvertFrom-Json
}

function Resolve-ProjectPython {
  # Project venv > WORKFLOW_PYTHON (user settings env) > PATH; validate each
  # (PATH `python` may be the Windows Store alias, exits 9009).
  param($Config, [string]$RepoRoot)
  $cands = @()
  if ($Config.python.venv) {
    $cands += Join-Path $RepoRoot ((($Config.python.venv) -replace '/', '\') + '\Scripts\python.exe')
  }
  $cands += @($env:WORKFLOW_PYTHON, 'python')
  foreach ($cand in $cands) {
    if (-not $cand) { continue }
    & $cand --version *> $null
    if ($LASTEXITCODE -eq 0) { return $cand }
  }
  throw "No working python found. Set WORKFLOW_PYTHON to a real interpreter."
}
