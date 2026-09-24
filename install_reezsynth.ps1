<# Installs Windows prerequisites, then creates and verifies the ReEzSynth environments. #>
[CmdletBinding()]
param(
    [string]$CondaExe = '',
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$EnvironmentName = 'reezsynth',
    [switch]$Plan,
    [switch]$CheckOnly,
    [switch]$SkipGit,
    [switch]$SkipConda,
    [switch]$SkipVisualStudio,
    [switch]$SkipCuda,
    [switch]$SkipEngineSetup,
    [switch]$NoLauncherConfig
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'ReEzSynth supports 64-bit Windows only.'
}
if ($Plan -and $CheckOnly) { throw 'Choose either -Plan or -CheckOnly.' }
if ($CheckOnly -and ($SkipGit -or $SkipConda -or $SkipVisualStudio -or $SkipCuda -or $SkipEngineSetup)) {
    throw 'Prerequisite selection switches cannot be combined with -CheckOnly.'
}

$wingetPackages = [ordered]@{
    Git = 'Git.Git'
    Conda = 'CondaForge.Miniforge3'
    VisualStudio = 'Microsoft.VisualStudio.2022.BuildTools'
    Cuda = 'Nvidia.CUDA'
}
$resumeMarker = Join-Path $PSScriptRoot '.reezsynth-setup-resume.json'
$resumeSetup = $false
$git = $null
$visualStudio = $null
$cuda = $null

function Find-Git {
    $command = Get-Command git.exe -ErrorAction SilentlyContinue
    $candidates = @()
    if ($command) { $candidates += $command.Source }
    if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles 'Git\cmd\git.exe' }
    if (${env:ProgramFiles(x86)}) { $candidates += Join-Path ${env:ProgramFiles(x86)} 'Git\cmd\git.exe' }
    if ($env:LOCALAPPDATA) { $candidates += Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe' }
    foreach ($candidate in ($candidates | Where-Object { $_ })) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $version = (& $candidate --version 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $version -match '^git version \d+\.\d+') {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Find-Conda {
    param([string]$Requested = '')
    $candidates = @($Requested, $env:CONDA_EXE)
    $command = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    foreach ($parent in @($env:USERPROFILE, $env:LOCALAPPDATA, $env:ProgramData)) {
        if ($parent) {
            foreach ($name in @('miniforge3', 'miniconda3', 'anaconda3')) {
                $candidates += Join-Path $parent "$name\Scripts\conda.exe"
            }
        }
    }
    foreach ($candidate in ($candidates | Where-Object { $_ })) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $version = (& $candidate --version 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $version -match '^conda \d+\.\d+') {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Find-Cuda128 {
    $candidates = @($env:CUDA_PATH_V12_8)
    $registry = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\NVIDIA Corporation\GPU Computing Toolkit\CUDA\v12.8' -ErrorAction SilentlyContinue
    $installDir = if ($registry) { $registry.PSObject.Properties['InstallDir'] } else { $null }
    if ($installDir -and $installDir.Value) { $candidates += $installDir.Value }
    if ($env:CUDA_PATH) { $candidates += $env:CUDA_PATH }
    if ($env:ProgramFiles) {
        $candidates += Join-Path $env:ProgramFiles 'NVIDIA GPU Computing Toolkit\CUDA\v12.8'
    }
    foreach ($root in $candidates | Where-Object { $_ }) {
        $nvcc = Join-Path $root 'bin\nvcc.exe'
        if (-not (Test-Path -LiteralPath $nvcc -PathType Leaf)) { continue }
        $version = (& $nvcc --version 2>&1 | Out-String)
        if ($LASTEXITCODE -eq 0 -and $version -match 'release\s+12\.8(?:\D|$)') {
            return (Resolve-Path -LiteralPath $root).Path
        }
    }
    return $null
}

function Find-VisualCppTools {
    $vswhereCandidates = @()
    if (${env:ProgramFiles(x86)}) {
        $vswhereCandidates += Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    }
    $command = Get-Command vswhere.exe -ErrorAction SilentlyContinue
    if ($command) { $vswhereCandidates += $command.Source }
    $vswhere = $vswhereCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        Select-Object -First 1
    if (-not $vswhere) { return $null }
    $path = (& $vswhere -products '*' -version '[17.0,18.0)' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath |
        Select-Object -First 1)
    if (-not $path) { return $null }
    $path = $path.Trim()
    $compiler = Get-ChildItem -LiteralPath (Join-Path $path 'VC\Tools\MSVC') -Filter cl.exe -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\bin\\Hostx64\\x64\\cl\.exe$' } | Select-Object -First 1
    if (-not $compiler) { return $null }
    $kits = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots' -ErrorAction SilentlyContinue
    $kitsRoot = if ($kits) { $kits.PSObject.Properties['KitsRoot10'].Value } else { $null }
    if (-not $kitsRoot) { return $null }
    $sdk = Get-ChildItem -LiteralPath (Join-Path $kitsRoot 'Include') -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName 'um\Windows.h') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName 'ucrt\stdio.h') -PathType Leaf)
        } | Select-Object -First 1
    if (-not $sdk) { return $null }
    return [pscustomobject]@{ InstallationPath = $path; MsvcCompiler = $compiler.FullName; WindowsSdk = $sdk.Name }
}

function Write-SkippedDependency {
    param([string]$Name, [string]$Impact)
    Write-Warning "$Name was unchecked and is not compatible or was not found. $Impact"
}

function Invoke-WingetInstall {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [string]$Version = '',
        [string]$Override = '',
        [switch]$Force
    )
    $arguments = @('install', '--id', $Id, '--exact', '--source', 'winget',
                   '--accept-package-agreements', '--accept-source-agreements',
                   '--disable-interactivity')
    if ($Version) { $arguments += @('--version', $Version) }
    if ($Override) { $arguments += @('--override', $Override) }
    if ($Force) { $arguments += '--force' }
    Write-Host ('WinGet arguments: ' + (ConvertTo-Json -InputObject $arguments -Compress))
    if ($Plan) { return }
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw 'Windows Package Manager (winget) is required to install the selected missing component. Install or update Microsoft App Installer, or clear that component and install it manually.'
    }
    & winget.exe @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "WinGet failed for '$Id' (exit $LASTEXITCODE). Existing installations and partial downloads were not removed."
    }
}

Write-Host 'ReEzSynth installation order:'
Write-Host '  1. NVIDIA GPU driver check'
Write-Host '  2. Git for Windows'
Write-Host '  3. Miniforge (Conda)'
Write-Host '  4. Visual Studio 2022 C++ Build Tools and Windows SDK'
Write-Host '  5. NVIDIA CUDA Toolkit 12.8'
Write-Host '  6. ReEzSynth Python environments, engines, checkpoints and verification'

if ($CheckOnly) {
    $CondaExe = Find-Conda -Requested $CondaExe
    if (-not $CondaExe) { throw 'Conda was not found, so the installed environments cannot be checked.' }
} else {
    if ((-not $SkipCuda -or -not $SkipEngineSetup) -and
        -not (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)) {
        if ($Plan) { Write-Warning 'An NVIDIA driver was not found; installation would stop before making changes.' }
        else { throw 'An NVIDIA driver was not found. Install the current driver for the NVIDIA GPU, restart Windows, and run this installer again.' }
    }
    $git = Find-Git
    if (-not $git) {
        if ($SkipGit) {
            Write-SkippedDependency -Name 'Git for Windows' -Impact 'FuouM source setup cannot complete without Git.'
        } else {
            Invoke-WingetInstall -Id $wingetPackages.Git
            $git = Find-Git
            if (-not $Plan -and -not $git) { throw 'Git installation completed but a working git.exe could not be located.' }
        }
    } else { Write-Host "Keeping existing Git: $git" }
    if ($git) { $env:Path = (Split-Path -Parent $git) + ';' + $env:Path }

    $CondaExe = Find-Conda -Requested $CondaExe
    if (-not $CondaExe) {
        if ($SkipConda) {
            Write-SkippedDependency -Name 'Miniforge/Conda' -Impact 'The ReEzSynth Python environment cannot be created and the application cannot run.'
        } else {
            Invoke-WingetInstall -Id $wingetPackages.Conda
            $CondaExe = Find-Conda
            if (-not $Plan -and -not $CondaExe) { throw 'Miniforge installation completed but a working conda.exe could not be located.' }
        }
    } else { Write-Host "Keeping existing Conda: $CondaExe" }
    if (-not $Plan -and $CondaExe) {
        $CondaExe = (Resolve-Path -LiteralPath $CondaExe).Path
        if (Test-Path -LiteralPath $resumeMarker -PathType Leaf) {
            try {
                $marker = Get-Content -LiteralPath $resumeMarker -Raw | ConvertFrom-Json
            } catch {
                throw "Setup resume marker is unreadable and was not changed: $resumeMarker"
            }
            $markerCondaText = if ($marker.PSObject.Properties['conda_exe']) { [string]$marker.conda_exe } else { '' }
            $markerEnvironment = if ($marker.PSObject.Properties['environment_name']) { [string]$marker.environment_name } else { '' }
            $markerConda = Resolve-Path -LiteralPath $markerCondaText -ErrorAction SilentlyContinue
            if ($markerEnvironment -ne $EnvironmentName -or
                -not $markerCondaText -or
                -not $markerConda -or $markerConda.Path -ne $CondaExe) {
                throw "Setup resume marker does not match this Conda executable and environment; existing environments were not modified: $resumeMarker"
            }
            $resumeSetup = $true
            Write-Host "Continuing the interrupted ReEzSynth setup recorded by: $resumeMarker"
        }
        $listing = & $CondaExe env list --json
        if ($LASTEXITCODE -ne 0) { throw 'Conda is installed, but its environment list could not be read.' }
        $existing = ($listing | Out-String | ConvertFrom-Json).envs | Where-Object {
            (Split-Path -Leaf $_) -eq $EnvironmentName
        } | Select-Object -First 1
        if ($existing -and -not $resumeSetup) {
            throw "Conda environment '$EnvironmentName' already exists at '$existing'. It was not modified. Run this script with -CheckOnly, or choose a new -EnvironmentName."
        }
        $fuoumEnvironment = Join-Path $PSScriptRoot '.engine_envs\fuoum'
        if ((Test-Path -LiteralPath $fuoumEnvironment) -and -not $resumeSetup) {
            throw "FuouM environment already exists at '$fuoumEnvironment'. It was not modified. Run this script with -CheckOnly, or use a fresh application folder."
        }
    }

    $visualStudio = Find-VisualCppTools
    if (-not $visualStudio) {
        if ($SkipVisualStudio) {
            Write-SkippedDependency -Name 'Visual Studio 2022 C++ Build Tools and Windows SDK' -Impact 'FuouM and native CUDA extensions cannot be built.'
        } else {
            Invoke-WingetInstall -Id $wingetPackages.VisualStudio -Force -Override '--passive --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended'
            $visualStudio = Find-VisualCppTools
            if (-not $Plan -and -not $visualStudio) {
                throw 'Visual Studio installation completed but the MSVC x64 compiler and a Windows 10/11 SDK were not both detected. Restart Windows, then run this installer again.'
            }
        }
    } else { Write-Host "Keeping existing Visual Studio C++ tools: $($visualStudio.InstallationPath) (Windows SDK $($visualStudio.WindowsSdk))" }

    $cuda = Find-Cuda128
    if (-not $cuda) {
        if ($SkipCuda) {
            Write-SkippedDependency -Name 'NVIDIA CUDA Toolkit 12.8' -Impact 'GPU engine setup, FuouM, and the Legacy CUDA extension cannot be built or validated.'
        } else {
            Invoke-WingetInstall -Id $wingetPackages.Cuda -Version '12.8'
            $cuda = Find-Cuda128
            if (-not $Plan -and -not $cuda) {
                throw 'CUDA installation completed but nvcc from the CUDA 12.8 toolkit was not detected. Restart Windows, then run this installer again.'
            }
        }
    } else { Write-Host "Keeping existing CUDA 12.8 toolkit: $cuda" }
    if ($cuda) {
        $env:CUDA_HOME = $cuda
        $env:CUDA_PATH = $cuda
        $env:Path = (Join-Path $cuda 'bin') + ';' + $env:Path
    }
}

if ($Plan) {
    Write-Host 'Plan only: no packages, environments or files were changed.'
    exit 0
}

if ($SkipEngineSetup) {
    Write-Warning 'ReEzSynth engine setup was unchecked. The application will not render until engine setup and validation are run from the Start menu.'
    exit 0
}

if (-not $CheckOnly) {
    $missing = @()
    if (-not $git) { $missing += 'Git for Windows' }
    if (-not $CondaExe) { $missing += 'Miniforge/Conda' }
    if (-not $visualStudio) { $missing += 'Visual Studio 2022 C++ Build Tools with a Windows SDK' }
    if (-not $cuda) { $missing += 'NVIDIA CUDA Toolkit 12.8 (nvcc)' }
    if ($missing.Count) {
        throw ('Engine setup cannot start because required components are unavailable: ' + ($missing -join ', ') + '. Rerun setup and select the missing components, or install compatible versions manually.')
    }
}

if (-not $CheckOnly -and -not $resumeSetup) {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $marker = [ordered]@{
        version = 2
        conda_exe = $CondaExe
        environment_name = $EnvironmentName
        fuoum_environment = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.engine_envs\fuoum'))
        created_utc = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json
    [IO.File]::WriteAllText($resumeMarker, $marker, $utf8)
}

$setup = Join-Path $PSScriptRoot 'setup_reezsynth.ps1'
if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) { throw "Missing engine setup script: $setup" }
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $setup,
               '-CondaExe', $CondaExe, '-EnvironmentName', $EnvironmentName)
if ($CheckOnly) { $arguments += '-CheckOnly' }
if ($resumeSetup) { $arguments += '-Resume' }
if ($NoLauncherConfig) { $arguments += '-NoLauncherConfig' }
& $powershell @arguments
if ($LASTEXITCODE -ne 0) { throw "ReEzSynth engine setup failed (exit $LASTEXITCODE). Inspect the preceding error; existing environments were not removed." }
if (-not $CheckOnly -and (Test-Path -LiteralPath $resumeMarker)) {
    Remove-Item -LiteralPath $resumeMarker -Force
}
Write-Host 'ReEzSynth prerequisites, engines and installation checks completed successfully.'
