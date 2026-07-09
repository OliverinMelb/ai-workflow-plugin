# PostToolUse hook (plugin engine, Edit|Write): fast maker check on the file
# just written. Exit 2 feeds stderr back to the model so it fixes the issue
# immediately. Which files to check and what to run comes from the project's
# workflow/config.json (auto_check section); projects without that config are
# skipped silently.

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
$repoRoot = git -C $cwd rev-parse --show-toplevel 2>$null
if (-not $repoRoot) { exit 0 }
$repoRoot = $repoRoot -replace '/', '\'

try {
  $config = Get-Content (Join-Path $repoRoot 'workflow\config.json') -Raw | ConvertFrom-Json
} catch {
  exit 0
}
$rule = $config.auto_check
if (-not $rule) { exit 0 }

if ($filePath -notlike "*$($rule.extension)") { exit 0 }
if ($filePath -notmatch [regex]::Escape($rule.path_contains)) { exit 0 }
if (-not (Test-Path $filePath)) { exit 0 }

# Resolve the interpreter: cmd "python" means project venv > WORKFLOW_PYTHON >
# PATH (PATH `python` may be the Windows Store alias, exits 9009).
$cmd = $rule.cmd
if ($cmd -eq 'python') {
  $venvPython = Join-Path $repoRoot ((($config.python.venv) -replace '/', '\') + '\Scripts\python.exe')
  $cmd = $null
  foreach ($cand in @($venvPython, $env:WORKFLOW_PYTHON, 'python')) {
    if (-not $cand) { continue }
    & $cand --version *> $null
    if ($LASTEXITCODE -eq 0) { $cmd = $cand; break }
  }
  if (-not $cmd) { exit 0 }  # no interpreter: skip silently rather than block every edit
}

$output = & $cmd @($rule.args) $filePath 2>&1
if ($LASTEXITCODE -ne 0) {
  [Console]::Error.WriteLine("auto-check failed on the file you just wrote. Fix before continuing:`n$($output | Out-String)")
  exit 2
}

exit 0
