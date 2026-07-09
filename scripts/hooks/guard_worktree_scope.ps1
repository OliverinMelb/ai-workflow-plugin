# PreToolUse hook (plugin engine, Edit|Write): enforce worktree boundaries.
# Exit 2 blocks the tool call; stderr is shown to the model as the reason.
# Rules:
#   - inside a linked worktree: writes must stay inside that worktree
#   - inside the main checkout: writes must not touch any linked worktree
# Applies only to projects with workflow/config.json in the MAIN checkout
# (the plugin is installed user-wide; other projects are left alone).

$ErrorActionPreference = 'Stop'

try {
  $raw = [Console]::In.ReadToEnd()
  $payload = $raw | ConvertFrom-Json
} catch {
  exit 0
}

$filePath = $payload.tool_input.file_path
if (-not $filePath) { exit 0 }

$cwd = $payload.cwd
if (-not $cwd) { $cwd = (Get-Location).Path }

function Normalize-Path([string]$p, [string]$base) {
  if (-not [System.IO.Path]::IsPathRooted($p)) {
    $p = Join-Path $base $p
  }
  try {
    return [System.IO.Path]::GetFullPath($p).TrimEnd('\').ToLowerInvariant()
  } catch {
    return $null
  }
}

$target = Normalize-Path $filePath $cwd
if (-not $target) { exit 0 }

# Resolve worktree layout from git itself (authoritative, no registry staleness)
$toplevel = (git -C $cwd rev-parse --show-toplevel 2>$null)
if (-not $toplevel) { exit 0 }
$toplevel = Normalize-Path ($toplevel -replace '/', '\') $cwd

$worktrees = @()
$rawWorktrees = @()
$porcelain = git -C $cwd worktree list --porcelain 2>$null
foreach ($line in $porcelain) {
  if ($line -match '^worktree (.+)$') {
    $rawWorktrees += ($Matches[1] -replace '/', '\')
    $worktrees += Normalize-Path ($Matches[1] -replace '/', '\') $cwd
  }
}
if ($worktrees.Count -eq 0) { exit 0 }

# Only enforce in workflow-enabled projects (config in the main checkout).
if (-not (Test-Path (Join-Path $rawWorktrees[0] 'workflow\config.json'))) { exit 0 }

$mainCheckout = $worktrees[0]  # first entry is always the main checkout
$inLinkedWorktree = ($toplevel -ne $mainCheckout)

if ($inLinkedWorktree) {
  if (-not $target.StartsWith($toplevel)) {
    [Console]::Error.WriteLine("BLOCKED by workflow guard: this session is bound to worktree '$toplevel'. Writing to '$target' is outside your assigned worktree (one subtask, one worktree).")
    exit 2
  }
} else {
  # Main-checkout sessions: warn (do not block) on writes into linked worktrees.
  # Harness-spawned implementer subagents inherit the main cwd, so a hard block
  # here would false-positive on legitimate subtask work. The hard guarantee
  # applies to sessions bound inside a worktree (rule above); implementer
  # agents must cd into their assigned worktree so that rule binds them.
  foreach ($wt in $worktrees) {
    if ($wt -ne $mainCheckout -and $target.StartsWith($wt)) {
      Write-Output "workflow guard: writing into linked worktree '$wt' from a main-checkout session. Legitimate only for the implementer subagent assigned to it."
    }
  }
}

exit 0
