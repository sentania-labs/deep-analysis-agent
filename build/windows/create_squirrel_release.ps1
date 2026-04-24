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
# --allowUnaware is required because the PyInstaller-produced EXE is not
# a Squirrel-aware .NET assembly — it has no embedded SquirrelAwareVersion
# manifest. With --allowUnaware, Squirrel skips install/update/uninstall
# hook invocation but still creates the Start Menu shortcut and delivers
# updates on next launch, which is the UX we want for a tray app.
Write-Host "Running Squirrel.exe pack (version $Version)..."
New-Item -ItemType Directory -Force -Path $ReleasesDir | Out-Null

& $Squirrel pack `
    --packId "DeepAnalysisAgent" `
    --packVersion $Version `
    --packAuthors "Sentania Labs" `
    --packDirectory $DistDir `
    --releaseDir $ReleasesDir `
    --allowUnaware
if ($LASTEXITCODE -ne 0) { Write-Error "Squirrel pack failed"; exit $LASTEXITCODE }

# --- Verify expected artifacts ---
# Clowd.Squirrel names the setup bundle "<packId>Setup.exe" — see
# SquirrelCli/Program.cs line 370: Path.Combine(di.FullName, $"{bundledzp.Id}Setup.exe").
$setupExe = Join-Path $ReleasesDir "DeepAnalysisAgentSetup.exe"
$releasesFile = Join-Path $ReleasesDir "RELEASES"
$nupkgs = Get-ChildItem -Path $ReleasesDir -Filter "*-full.nupkg" -ErrorAction SilentlyContinue

if (-not (Test-Path $setupExe))    { Write-Error "Squirrel output missing: $setupExe"; exit 1 }
if (-not (Test-Path $releasesFile)) { Write-Error "Squirrel output missing: $releasesFile"; exit 1 }
if (-not $nupkgs -or $nupkgs.Count -lt 1) { Write-Error "Squirrel output missing: no *-full.nupkg in $ReleasesDir"; exit 1 }

Write-Host "Release artifacts written to $ReleasesDir"
Get-ChildItem $ReleasesDir | Format-Table Name, Length
