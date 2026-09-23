[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?$')]
    [string]$Version,
    [string]$InnoCompiler = '',
    [switch]$SourceOnly,
    [switch]$Plan
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$numericVersion = ([regex]::Match($Version, '^\d+\.\d+\.\d+')).Value + '.0'
$commit = (& git -C $root rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
    throw 'Release packaging requires a Git checkout with a valid HEAD commit.'
}
$status = (& git -C $root status --porcelain --untracked-files=normal | Out-String).Trim()
if ($status) {
    throw 'Release packaging requires a clean working tree so every artifact maps to one reviewed commit.'
}

$dist = [IO.Path]::GetFullPath((Join-Path $root 'dist'))
$sourceName = "ReEzSynth-$Version-source.zip"
$installerName = "ReEzSynth-Windows-$Version.exe"
if ($Plan) {
    [ordered]@{
        version = $Version
        commit = $commit
        source = (Join-Path $dist $sourceName)
        installer = if ($SourceOnly) { $null } else { Join-Path $dist $installerName }
        publishes_release = $false
        requires_clean_tree = $true
    } | ConvertTo-Json
    exit 0
}

function Remove-ReleaseDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    $expected = [IO.Path]::GetFullPath((Join-Path $root 'dist'))
    if ($resolved -ne $expected) { throw "Refusing to remove unexpected directory: $resolved" }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

Remove-ReleaseDirectory -Path $dist
New-Item -ItemType Directory -Path $dist | Out-Null
$sourceZip = Join-Path $dist $sourceName
& git -C $root archive --format=zip --prefix="ReEzSynth-$Version/" --output=$sourceZip HEAD
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $sourceZip -PathType Leaf)) {
    throw 'Git could not create the source archive.'
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($sourceZip)
try {
    $prefix = "ReEzSynth-$Version/"
    $forbiddenParts = @('/examples/', '/diagnostic_outputs/', '/engine_sources/',
                        '/.engine_envs/', '/backups/', '/reezsynth_outputs/',
                        '/reezsynth_projects/', '/renders/', '/outputs/',
                        '/output_synth/', '/.reezsynth-cache/')
    $forbiddenExtensions = @('.bmp', '.gif', '.jpeg', '.jpg', '.png', '.tif', '.tiff', '.webp')
    $violations = @()
    foreach ($entry in $archive.Entries) {
        $name = $entry.FullName.Replace('\', '/')
        if (-not $name.StartsWith($prefix, [StringComparison]::Ordinal)) {
            $violations += $name
            continue
        }
        $relative = $name.Substring($prefix.Length)
        $wrapped = '/' + $relative.ToLowerInvariant()
        if ($forbiddenParts | Where-Object { $wrapped.Contains($_) }) { $violations += $name; continue }
        if ($forbiddenExtensions -contains [IO.Path]::GetExtension($relative).ToLowerInvariant()) {
            $violations += $name
        }
    }
    if ($violations) {
        throw "Release archive contains forbidden local/example media paths:`n$($violations -join "`n")"
    }
} finally {
    $archive.Dispose()
}

$artifacts = @($sourceZip)
if (-not $SourceOnly) {
    if (-not $InnoCompiler) {
        $candidates = @(
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe')
        )
        $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($command) { $candidates += $command.Source }
        $InnoCompiler = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
    }
    if (-not $InnoCompiler) { throw 'Inno Setup compiler not found. Supply -InnoCompiler or use -SourceOnly.' }

    $stage = Join-Path $dist '.installer-stage'
    Expand-Archive -LiteralPath $sourceZip -DestinationPath $stage
    $sourceRoot = Join-Path $stage "ReEzSynth-$Version"
    & $InnoCompiler "/DMyAppVersion=$Version" "/DMyNumericVersion=$numericVersion" "/DSourceDir=$sourceRoot" "/DOutputDir=$dist" "/DCommit=$commit" (Join-Path $root 'installer\ReEzSynth.iss')
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE." }
    $installer = Join-Path $dist $installerName
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw "Installer was not created: $installer" }
    $artifacts += $installer
    $resolvedStage = [IO.Path]::GetFullPath($stage)
    if (-not $resolvedStage.StartsWith($dist + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove unexpected staging directory: $resolvedStage"
    }
    Remove-Item -LiteralPath $resolvedStage -Recurse -Force
}

$hashLines = foreach ($artifact in $artifacts) {
    $hash = Get-Sha256 -Path $artifact
    "$hash  $([IO.Path]::GetFileName($artifact))"
}
$hashPath = Join-Path $dist 'SHA256SUMS.txt'
[IO.File]::WriteAllLines($hashPath, $hashLines, (New-Object Text.UTF8Encoding($false)))
$manifest = [ordered]@{
    version = $Version
    commit = $commit
    artifacts = @($artifacts | ForEach-Object { [IO.Path]::GetFileName($_) })
    checksums = [IO.Path]::GetFileName($hashPath)
    examples_or_raster_media_included = $false
    release_published = $false
} | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $dist 'RELEASE_MANIFEST.json'), $manifest,
                        (New-Object Text.UTF8Encoding($false)))
Write-Host "Release artifacts created under $dist for commit $commit."
