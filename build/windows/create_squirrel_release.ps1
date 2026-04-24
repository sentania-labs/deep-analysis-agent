# Create Squirrel.Windows release package.
# Prereqs: nuget CLI + Squirrel installed; PyInstaller build done (dist/deep-analysis-agent/ exists).
# Output: Releases/ directory with RELEASES, Setup.exe, Setup.msi, *-full.nupkg

param(
    [Parameter(Mandatory)]
    [string]$Version,   # e.g. "0.4.0" (no leading v)

    [string]$SquirrelPath = "",   # Override path to Squirrel.exe if not on PATH
    [string]$NugetPath    = ""    # Override path to nuget.exe if not on PATH
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path "$PSScriptRoot\..\.."
$BuildDir = "$PSScriptRoot"
$ReleasesDir = "$RepoRoot\Releases"

Set-Location $BuildDir

# --- Resolve tools ---
$Squirrel = if ($SquirrelPath) { $SquirrelPath } else { "Squirrel.exe" }
$Nuget    = if ($NugetPath) { $NugetPath } else { "nuget.exe" }

# Install Squirrel via Chocolatey if not found
if (-not (Get-Command $Squirrel -ErrorAction SilentlyContinue)) {
    Write-Host "Squirrel not found — installing via Chocolatey..."
    choco install squirrel-windows --yes
    $Squirrel = "Squirrel.exe"
}

# --- Verify dist exists ---
$DistDir = "$RepoRoot\dist\deep-analysis-agent"
if (-not (Test-Path $DistDir)) {
    Write-Error "PyInstaller output not found at $DistDir — run build_pyinstaller.ps1 first."
    exit 1
}

# --- Pack NuGet ---
Write-Host "Packing NuGet package (version $Version)..."
$NuspecPath = "deep-analysis-agent.nuspec"
& $Nuget pack $NuspecPath -Version $Version -OutputDirectory $RepoRoot -NonInteractive
if ($LASTEXITCODE -ne 0) { Write-Error "nuget pack failed"; exit $LASTEXITCODE }

$NupkgPath = "$RepoRoot\DeepAnalysisAgent.$Version.nupkg"

# --- Releasify ---
Write-Host "Running Squirrel --releasify..."
New-Item -ItemType Directory -Force -Path $ReleasesDir | Out-Null
& $Squirrel --releasify $NupkgPath --releaseDir $ReleasesDir --no-msi:$false
if ($LASTEXITCODE -ne 0) { Write-Error "Squirrel releasify failed"; exit $LASTEXITCODE }

Write-Host "Release artifacts written to $ReleasesDir"
Get-ChildItem $ReleasesDir | Format-Table Name, Length
