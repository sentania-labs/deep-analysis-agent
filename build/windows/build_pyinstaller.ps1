# Build script for Deep Analysis Agent (Windows only).
# Requires: uv installed and `uv sync --extra build` run first.
# Output: dist/deep-analysis-agent/ (one-folder, Squirrel-ready)

param(
    [switch]$Clean
)

$RepoRoot = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $RepoRoot

if ($Clean) {
    Write-Host "Cleaning dist/ and build/..."
    Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
}

Write-Host "Running PyInstaller..."
uv run pyinstaller build/windows/deep-analysis-agent.spec --noconfirm

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Build complete: dist/deep-analysis-agent/"
