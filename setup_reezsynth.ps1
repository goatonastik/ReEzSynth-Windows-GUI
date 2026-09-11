<# Creates a dedicated Windows environment. Never repairs or replaces an existing one. #>
[CmdletBinding()]
param(
    [string]$CondaExe = '',
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$EnvironmentName = 'reezsynth',
    [switch]$Plan,
    [switch]$CheckOnly,
    [switch]$NoLauncherConfig
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'This setup supports 64-bit Windows only.'
}
if ($EnvironmentName -eq 'base') { throw 'Do not install ReEzSynth into base Conda.' }
if ($Plan -and $CheckOnly) { throw 'Choose either -Plan or -CheckOnly.' }

if (-not $CondaExe) {
    $candidates = @($env:CONDA_EXE)
    $command = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    foreach ($parent in @($env:USERPROFILE, $env:LOCALAPPDATA, $env:ProgramData)) {
        if ($parent) {
            foreach ($name in @('miniconda3', 'anaconda3', 'miniforge3')) {
                $candidates += Join-Path $parent "$name\Scripts\conda.exe"
            }
        }
    }
    $CondaExe = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
}
if (-not $CondaExe -or -not (Test-Path -LiteralPath $CondaExe -PathType Leaf)) {
    throw 'Conda not found. Install Miniforge/Miniconda, or supply -CondaExe C:\path\Scripts\conda.exe. See INSTALL_WINDOWS.md.'
}
$CondaExe = (Resolve-Path -LiteralPath $CondaExe).Path

function Invoke-CondaStep {
    param([string[]]$Arguments)
    Write-Host ('Conda arguments: ' + (ConvertTo-Json -InputObject $Arguments -Compress))
    if (-not $Plan) {
        & $CondaExe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Conda step failed (exit $LASTEXITCODE). The environment was not deleted; inspect the error before retrying." }
    }
}

$run = @('run', '--no-capture-output', '-n', $EnvironmentName)
if ($CheckOnly) {
    Invoke-CondaStep -Arguments ($run + @('python', '-X', 'utf8', (Join-Path $PSScriptRoot 'check_reezsynth.py'), '--gui-smoke', '--cuda', '--native', '--raft-extension'))
    exit 0
}
if (-not $Plan) {
    $listing = & $CondaExe env list --json
    if ($LASTEXITCODE -ne 0) { throw 'Could not enumerate existing Conda environments.' }
    $environments = ($listing | Out-String | ConvertFrom-Json).envs
    foreach ($path in $environments) {
        if ((Split-Path -Leaf $path) -eq $EnvironmentName) {
            throw "Environment '$EnvironmentName' already exists. Use -CheckOnly to diagnose it, or choose a new -EnvironmentName. Existing environments are never overwritten."
        }
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    Invoke-CondaStep -Arguments @('create', '--yes', '--override-channels', '-c', 'conda-forge', '-n', $EnvironmentName, 'python=3.11', 'pip')
    Invoke-CondaStep -Arguments ($run + @('python', '-c', 'import sys; assert sys.version_info[:2] == (3,11) and sys.maxsize > 2**32; print(sys.executable)'))
    Invoke-CondaStep -Arguments ($run + @('python', '-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'requirements-torch-cu128.txt'))
    Invoke-CondaStep -Arguments ($run + @('python', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '--require-hashes', '-r', 'requirements-raft-extension.txt'))
    Invoke-CondaStep -Arguments ($run + @('python', '-m', 'pip', 'install', '--disable-pip-version-check', '--index-url', 'https://pypi.org/simple', '-r', 'requirements.txt', '-c', 'reezsynth-working-requirements.txt'))
    Invoke-CondaStep -Arguments ($run + @('python', '-m', 'pip', 'check'))
    Invoke-CondaStep -Arguments ($run + @('python', '-X', 'utf8', 'check_reezsynth.py', '--gui-smoke', '--cuda', '--native', '--raft-extension'))
    if ($Plan) { Write-Host 'Plan only: no environment or packages changed.' }
    else {
        if (-not $NoLauncherConfig) {
            $utf8 = New-Object System.Text.UTF8Encoding($false)
            [IO.File]::WriteAllText((Join-Path $PSScriptRoot '.reezsynth-conda-path.txt'), $CondaExe, $utf8)
            [IO.File]::WriteAllText((Join-Path $PSScriptRoot '.reezsynth-env-name.txt'), $EnvironmentName, $utf8)
        }
        Write-Host "Setup checks passed. Activate '$EnvironmentName' and run .\run_reezsynth.bat."
        Write-Host 'No GPU render was performed; validate one short render before production use.'
        if ($NoLauncherConfig -and $EnvironmentName -ne 'reezsynth') { Write-Host "Set REEZSYNTH_ENV=$EnvironmentName when using the launcher." }
    }
} finally { Pop-Location }
