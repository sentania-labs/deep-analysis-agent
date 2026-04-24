# Create Clowd.Squirrel release package.
# Prereqs: Clowd.Squirrel installed via `nuget install Clowd.Squirrel -ExcludeVersion -OutputDirectory tools`
#          PyInstaller build done (dist/deep-analysis-agent/ exists).
# Output: Releases/ directory with RELEASES, Setup.exe, *-full.nupkg

param(
    [Parameter(Mandatory)]
    [string]$Version,   # e.g. "0.4.0" (no leading v)

    [string]$SquirrelPath = ""   # Override path to Squirrel.exe
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path "$PSScriptRoot\..\.."
$ReleasesDir = "$RepoRoot\Releases"

# --- Resolve Squirrel.exe from Clowd.Squirrel NuGet package ---
if ($SquirrelPath) {
    $Squirrel = $SquirrelPath
} else {
    $candidate = "$RepoRoot\tools\Clowd.Squirrel\tools\Squirrel.exe"
    if (-not (Test-Path $candidate)) {
        Write-Error "Squirrel.exe not found at $candidate. Install via: nuget install Clowd.Squirrel -ExcludeVersion -OutputDirectory tools"
        exit 1
    }
    $Squirrel = $candidate
}

# --- Verify dist exists ---
$DistDir = "$RepoRoot\dist\deep-analysis-agent"
if (-not (Test-Path $DistDir)) {
    Write-Error "PyInstaller output not found at $DistDir — run build_pyinstaller.ps1 first."
    exit 1
}

# --- Pack with Clowd.Squirrel ---
Write-Host "Running Squirrel.exe pack (version $Version)..."
New-Item -ItemType Directory -Force -Path $ReleasesDir | Out-Null

& $Squirrel pack `
    --packId "DeepAnalysisAgent" `
    --packVersion $Version `
    --packAuthors "Sentania Labs" `
    --packDirectory $DistDir `
    --releaseDir $ReleasesDir
if ($LASTEXITCODE -ne 0) { Write-Error "Squirrel pack failed"; exit $LASTEXITCODE }

Write-Host "Release artifacts written to $ReleasesDir"
Get-ChildItem $ReleasesDir | Format-Table Name, Length
