<# Installs both synthesis engines. Never repairs or replaces existing environments. #>
[CmdletBinding()]
param(
    [string]$CondaExe = '',
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$EnvironmentName = 'reezsynth',
    [switch]$Plan,
    [switch]$CheckOnly,
    [switch]$Resume,
    [switch]$NoLauncherConfig
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'This setup supports 64-bit Windows only.'
}
if ($EnvironmentName -eq 'base') { throw 'Do not install ReEzSynth into base Conda.' }
if (([int][bool]$Plan + [int][bool]$CheckOnly + [int][bool]$Resume) -gt 1) {
    throw 'Choose only one of -Plan, -CheckOnly, or -Resume.'
}

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

if ($Resume) {
    $resumeMarker = Join-Path $PSScriptRoot '.reezsynth-setup-resume.json'
    if (-not (Test-Path -LiteralPath $resumeMarker -PathType Leaf)) {
        throw "Resume requires the setup marker created by install_reezsynth.ps1: $resumeMarker"
    }
    try {
        $marker = Get-Content -LiteralPath $resumeMarker -Raw | ConvertFrom-Json
    } catch {
        throw "Setup resume marker is unreadable and was not changed: $resumeMarker"
    }
    $markerCondaText = if ($marker.PSObject.Properties['conda_exe']) { [string]$marker.conda_exe } else { '' }
    $markerEnvironment = if ($marker.PSObject.Properties['environment_name']) { [string]$marker.environment_name } else { '' }
    $markerConda = Resolve-Path -LiteralPath $markerCondaText -ErrorAction SilentlyContinue
    if (-not $markerConda -or $CondaExe -ne $markerConda.Path -or
        $markerEnvironment -ne $EnvironmentName) {
        $savedPath = if ($markerConda) { $markerConda.Path } else { $markerCondaText }
        throw "Resume marker does not exactly match the requested Conda executable and environment name. Requested '$CondaExe' / '$EnvironmentName'; saved '$savedPath' / '$markerEnvironment'. Existing environments were not modified."
    }
}

function Invoke-CondaStep {
    param([string[]]$Arguments)
    Write-Host ('Conda arguments: ' + (ConvertTo-Json -InputObject $Arguments -Compress))
    if (-not $Plan) {
        & $CondaExe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Conda step failed (exit $LASTEXITCODE). The environment was not deleted; inspect the error before retrying." }
    }
}

$run = @('run', '--no-capture-output', '-n', $EnvironmentName)
$matchingEnvironment = $null
if ($CheckOnly) {
    Invoke-CondaStep -Arguments ($run + @('python', '-X', 'utf8', (Join-Path $PSScriptRoot 'check_reezsynth.py'), '--gui-smoke', '--cuda', '--native', '--raft-extension'))
    Invoke-CondaStep -Arguments ($run + @('python', '-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'setup_fuoum.py'), '--check-only', '--neuflow'))
    Write-Host 'Both synthesis engines passed installation checks.'
    exit 0
}
if (-not $Plan) {
    $listing = & $CondaExe env list --json
    if ($LASTEXITCODE -ne 0) { throw 'Could not enumerate existing Conda environments.' }
    $environments = ($listing | Out-String | ConvertFrom-Json).envs
    $matchingEnvironment = $environments | Where-Object {
        (Split-Path -Leaf $_) -eq $EnvironmentName
    } | Select-Object -First 1
    if ($matchingEnvironment -and -not $Resume) {
        throw "Environment '$EnvironmentName' already exists. Use -CheckOnly to diagnose it, -Resume only for this setup's interrupted installation, or choose a new -EnvironmentName. Existing environments are never overwritten."
    }
    if ($Resume -and -not $matchingEnvironment) {
        Write-Host "Resume requested, but environment '$EnvironmentName' does not exist; creating it now."
    }
    $fuoumEnvironment = Join-Path $PSScriptRoot '.engine_envs\fuoum'
    if ((Test-Path -LiteralPath $fuoumEnvironment) -and -not $Resume) {
        throw "FuouM environment already exists at '$fuoumEnvironment'. Use -CheckOnly, -Resume only for this setup's interrupted installation, or install into a fresh application folder. Existing environments are never overwritten."
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not $matchingEnvironment) {
        Invoke-CondaStep -Arguments @('create', '--yes', '--override-channels', '-c', 'conda-forge', '-n', $EnvironmentName, 'python=3.11', 'pip')
    } else {
        Write-Host "Resuming existing setup environment: $matchingEnvironment"
    }
    Invoke-CondaStep -Arguments ($run + @('python', '-c', 'import sys; assert sys.version_info[:2] == (3,11) and sys.maxsize > 2**32; print(sys.executable)'))
    # Uses only the new environment's standard library; check build tools before large downloads.
    Invoke-CondaStep -Arguments ($run + @('python', '-B', '-X', 'utf8', 'setup_fuoum.py', '--preflight'))
    Invoke-CondaStep -Arguments ($run + @('python', '-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'requirements-torch-cu128.txt'))
    Invoke-CondaStep -Arguments ($run + @('python', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '--require-hashes', '-r', 'requirements-raft-extension.txt'))
    Invoke-CondaStep -Arguments ($run + @('python', '-m', 'pip', 'install', '--disable-pip-version-check', '--index-url', 'https://pypi.org/simple', '-r', 'requirements.txt', '-c', 'reezsynth-working-requirements.txt'))
    Invoke-CondaStep -Arguments ($run + @('python', '-m', 'pip', 'check'))
    Invoke-CondaStep -Arguments ($run + @('python', '-X', 'utf8', 'check_reezsynth.py', '--gui-smoke', '--cuda', '--native', '--raft-extension'))
    $fuoumArguments = $run + @('python', '-B', '-X', 'utf8', 'setup_fuoum.py', '--neuflow')
    if ($Resume) { $fuoumArguments += '--resume' }
    Invoke-CondaStep -Arguments $fuoumArguments
    if ($Plan) { Write-Host 'Plan only: no environment or packages changed.' }
    else {
        if (-not $NoLauncherConfig) {
            $utf8 = New-Object System.Text.UTF8Encoding($false)
            [IO.File]::WriteAllText((Join-Path $PSScriptRoot '.reezsynth-conda-path.txt'), $CondaExe, $utf8)
            [IO.File]::WriteAllText((Join-Path $PSScriptRoot '.reezsynth-env-name.txt'), $EnvironmentName, $utf8)
        }
        Write-Host "Both synthesis engines are installed and checked. Activate '$EnvironmentName' and run .\run_reezsynth.bat."
        Write-Host 'No GPU render was performed; validate one short render before production use.'
        if ($NoLauncherConfig -and $EnvironmentName -ne 'reezsynth') { Write-Host "Set REEZSYNTH_ENV=$EnvironmentName when using the launcher." }
    }
} finally { Pop-Location }
