param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$WorkflowArgs
)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'workflow_cli.py'
$candidates = New-Object System.Collections.Generic.List[string]

if ($env:WORKFLOW_PYTHON) {
  $candidates.Add($env:WORKFLOW_PYTHON)
}

try {
  $repoRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
  if ($repoRoot) {
    $configPath = Join-Path $repoRoot 'workflow\config.json'
    if (Test-Path -LiteralPath $configPath) {
      $config = Get-Content -Raw -Encoding UTF8 -LiteralPath $configPath | ConvertFrom-Json
      if ($config.python.venv) {
        $venvPython = Join-Path $repoRoot ($config.python.venv -replace '/', '\')
        $venvPython = Join-Path $venvPython 'Scripts\python.exe'
        $candidates.Add($venvPython)
      }
    }
  }
} catch {
  # The Python CLI reports repository/config errors with structured messages.
}

$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand -and $pythonCommand.Source -notmatch '\\WindowsApps\\') {
  $candidates.Add($pythonCommand.Source)
}

$runtimePythons = Get-ChildItem -Path (Join-Path $env:USERPROFILE '.cache\codex-runtimes') -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match '\\dependencies\\python\\python.exe$' } |
  Select-Object -ExpandProperty FullName
foreach ($runtimePython in $runtimePythons) {
  $candidates.Add($runtimePython)
}

foreach ($candidate in ($candidates | Select-Object -Unique)) {
  if ($candidate -and (Test-Path -LiteralPath $candidate)) {
    & $candidate -X utf8 $scriptPath @WorkflowArgs
    exit $LASTEXITCODE
  }
}

$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pyLauncher) {
  & $pyLauncher.Source -3 -X utf8 $scriptPath @WorkflowArgs
  exit $LASTEXITCODE
}

throw 'No usable Python interpreter found. Set WORKFLOW_PYTHON to a real python.exe.'
