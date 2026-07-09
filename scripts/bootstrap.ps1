# Idempotent environment bootstrap for the main checkout and for worktrees.
# Generic engine: all project specifics (component dirs, probe modules,
# install env) come from the project's workflow/config.json.
# See the plugin README for component semantics; worktree fast path: node
# components get a junction to the main checkout's node_modules (zero
# installs), python components share the main venv.

param(
  [string]$TargetRoot
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_lib.ps1')

$repoRoot = Get-MainRoot
$config = Get-WorkflowConfig $repoRoot
if (-not $TargetRoot) { $TargetRoot = $repoRoot }
$TargetRoot = (Resolve-Path $TargetRoot).Path

# A linked worktree has a `.git` FILE (gitdir pointer); the main checkout has
# a `.git` directory.
$isWorktree = Test-Path (Join-Path $TargetRoot '.git') -PathType Leaf

# Components by type, from config
$pythonComponents = @()
$nodeComponents = @()
foreach ($prop in $config.components.PSObject.Properties) {
  $comp = $prop.Value
  if ($comp.type -eq 'python-venv') { $pythonComponents += $comp }
  elseif ($comp.type -eq 'node') { $nodeComponents += $comp }
}

function Resolve-BasePython {
  foreach ($cand in @($env:WORKFLOW_PYTHON, 'python')) {
    if (-not $cand) { continue }
    & $cand --version *> $null
    if ($LASTEXITCODE -eq 0) { return $cand }
  }
  throw "No working python found. Set WORKFLOW_PYTHON to a real interpreter."
}

function Test-PythonComponentReady {
  param([string]$Root, $Component)
  $venvPython = Join-Path $Root "$($Component.dir)\.venv\Scripts\python.exe"
  if (-not (Test-Path $venvPython)) { return $false }
  $imports = ($Component.probe_imports | ForEach-Object { "import $_" }) -join '; '
  & $venvPython -c $imports *> $null
  return ($LASTEXITCODE -eq 0)
}

function Test-NodeComponentReady {
  param([string]$Root, $Component)
  $compDir = Join-Path $Root $Component.dir
  if (-not (Test-Path (Join-Path $compDir 'node_modules'))) { return $false }
  # dir-exists is not enough (npm ci can be interrupted): resolve the actual
  # modules the verification matrix needs.
  $probes = ($Component.probe_modules | ForEach-Object { "require.resolve('$_');" }) -join ' '
  Push-Location $compDir
  try {
    & node -e $probes *> $null
    return ($LASTEXITCODE -eq 0)
  } finally {
    Pop-Location
  }
}

function Install-PythonComponent {
  param([string]$Root, $Component)
  $compDir = Join-Path $Root $Component.dir
  $venvPython = Join-Path $compDir '.venv\Scripts\python.exe'
  $python = Resolve-BasePython
  Write-Output "[bootstrap] $($Component.dir): creating venv + installing pyproject deps"
  if (-not (Test-Path $venvPython)) {
    & $python -m venv (Join-Path $compDir '.venv')
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
  }
  # Read [project].dependencies so the list never drifts from pyproject.toml.
  $pyprojectPath = Join-Path $compDir 'pyproject.toml'
  $deps = & $venvPython -c "import tomllib; print('\n'.join(tomllib.load(open(r'$pyprojectPath','rb'))['project']['dependencies']))"
  if ($LASTEXITCODE -ne 0) { throw "failed to read dependencies from pyproject.toml" }
  $depList = @($deps -split "`r?`n" | Where-Object { $_ })
  # Default PyPI on purpose: regional mirrors can fail with SSL EOF under VPN
  # proxies (see global environment memory).
  & $venvPython -m pip install --index-url https://pypi.org/simple @depList
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

function Install-NodeComponent {
  param([string]$Root, $Component)
  $compDir = Join-Path $Root $Component.dir
  Write-Output "[bootstrap] $($Component.dir): npm ci"
  Push-Location $compDir
  $savedEnv = @{}
  try {
    # Apply component install_env (e.g. ELECTRON_SKIP_BINARY_DOWNLOAD=1).
    if ($Component.install_env) {
      foreach ($prop in $Component.install_env.PSObject.Properties) {
        $savedEnv[$prop.Name] = [Environment]::GetEnvironmentVariable($prop.Name)
        [Environment]::SetEnvironmentVariable($prop.Name, $prop.Value)
      }
    }
    $ErrorActionPreference = 'Continue'   # npm writes progress to stderr
    & npm ci 2>&1 | ForEach-Object { "$_" } | Select-Object -Last 5
    $code = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = 'Stop'
    foreach ($name in $savedEnv.Keys) {
      [Environment]::SetEnvironmentVariable($name, $savedEnv[$name])
    }
    Pop-Location
  }
  if ($code -ne 0) { throw "npm ci failed (exit $code)" }
}

if ($isWorktree) {
  # ---- Worktree fast path: shared deps, zero installs -----------------------
  Write-Output "[bootstrap] worktree mode: $TargetRoot"

  foreach ($comp in $pythonComponents) {
    # Nothing to provision in the worktree - verification runs checks with the
    # main checkout's venv. Just make sure that venv is healthy.
    if (-not (Test-PythonComponentReady $repoRoot $comp)) { Install-PythonComponent $repoRoot $comp }
    else { Write-Output "[bootstrap] $($comp.dir): main venv OK (shared)" }
  }

  foreach ($comp in $nodeComponents) {
    $wtNodeModules = Join-Path $TargetRoot "$($comp.dir)\node_modules"
    if (Test-Path $wtNodeModules) {
      Write-Output "[bootstrap] $($comp.dir): node_modules already present (no-op)"
    } else {
      # Junction source must be complete before linking.
      if (-not (Test-NodeComponentReady $repoRoot $comp)) { Install-NodeComponent $repoRoot $comp }
      $mainNodeModules = Join-Path $repoRoot "$($comp.dir)\node_modules"
      New-Item -ItemType Junction -Path $wtNodeModules -Target $mainNodeModules | Out-Null
      Write-Output "[bootstrap] $($comp.dir): junction -> $mainNodeModules"
    }
    if (-not (Test-NodeComponentReady $TargetRoot $comp)) {
      throw "$($comp.dir): deps not resolvable through the junction (fall back to npm ci per worktree and record why)"
    }
  }
} else {
  # ---- Main checkout --------------------------------------------------------
  Write-Output "[bootstrap] main checkout mode: $TargetRoot"

  foreach ($comp in $pythonComponents) {
    if (Test-PythonComponentReady $TargetRoot $comp) {
      Write-Output "[bootstrap] $($comp.dir): venv OK (no-op)"
    } else {
      Install-PythonComponent $TargetRoot $comp
      if (-not (Test-PythonComponentReady $TargetRoot $comp)) { throw "$($comp.dir) still not ready after install" }
    }
  }

  foreach ($comp in $nodeComponents) {
    if (Test-NodeComponentReady $TargetRoot $comp) {
      Write-Output "[bootstrap] $($comp.dir): node_modules OK (no-op)"
    } else {
      Install-NodeComponent $TargetRoot $comp
      if (-not (Test-NodeComponentReady $TargetRoot $comp)) { throw "$($comp.dir) still not ready after npm ci" }
    }
  }
}

Write-Output "[bootstrap] done: environment ready at $TargetRoot"
