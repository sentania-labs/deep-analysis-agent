param(
    [string]$SquirrelPath = "tools\Clowd.Squirrel\tools\Squirrel.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path "$PSScriptRoot\..\.."
$Squirrel = Resolve-Path (Join-Path $RepoRoot $SquirrelPath)
$Payload = Resolve-Path (Join-Path $RepoRoot "dist\deep-analysis-agent")
$TestRoot = Join-Path $env:RUNNER_TEMP "deep-analysis-agent-updater-e2e"
$LocalAppData = Join-Path $TestRoot "LocalAppData"
$ShellFolders = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
$OriginalLocalAppData = Get-ItemPropertyValue -Path $ShellFolders -Name "Local AppData"

function Invoke-SquirrelPack {
    param(
        [Parameter(Mandatory)]
        [string]$PackId,
        [Parameter(Mandatory)]
        [string]$Version,
        [Parameter(Mandatory)]
        [string]$ReleaseDir
    )

    & $Squirrel pack `
        --packId $PackId `
        --packVersion $Version `
        --packAuthors "Sentania Labs" `
        --packDirectory $Payload `
        --releaseDir $ReleaseDir `
        --allowUnaware `
        --noDelta
    if ($LASTEXITCODE -ne 0) {
        throw "Squirrel pack failed for $PackId $Version"
    }
}

function Install-SquirrelPackage {
    param(
        [Parameter(Mandatory)]
        [string]$PackId,
        [Parameter(Mandatory)]
        [string]$ReleaseDir
    )

    $Setup = Join-Path $ReleaseDir "$($PackId)Setup.exe"
    $Process = Start-Process -FilePath $Setup -ArgumentList "--silent" -Wait -PassThru
    if ($Process.ExitCode -ne 0) {
        throw "$PackId setup failed with exit $($Process.ExitCode)"
    }

    $AppRoot = Join-Path $LocalAppData $PackId
    if (-not (Test-Path (Join-Path $AppRoot "Update.exe"))) {
        throw "$PackId did not install Update.exe into $AppRoot"
    }
    return $AppRoot
}

function New-StalledUpdateExe {
    param(
        [Parameter(Mandatory)]
        [string]$OutputPath
    )

    $Source = @"
using System.Threading;

public static class Program
{
    public static int Main(string[] args)
    {
        Thread.Sleep(2000);
        return 0;
    }
}
"@
    Add-Type -TypeDefinition $Source -Language CSharp `
        -OutputAssembly $OutputPath -OutputType ConsoleApplication
}

if (Test-Path $TestRoot) {
    Remove-Item -Recurse -Force $TestRoot
}
New-Item -ItemType Directory -Force -Path $LocalAppData | Out-Null

try {
    Set-ItemProperty -Path $ShellFolders -Name "Local AppData" -Value $LocalAppData
    $env:LOCALAPPDATA = $LocalAppData

    $GoodFeed = Join-Path $TestRoot "good-feed"
    $NoUpdateFeed = Join-Path $TestRoot "no-update-feed"
    $GoodPackId = "DeepAnalysisAgentE2EGood"
    Invoke-SquirrelPack -PackId $GoodPackId -Version "0.0.1" -ReleaseDir $GoodFeed
    Copy-Item -Recurse -Path $GoodFeed -Destination $NoUpdateFeed
    Invoke-SquirrelPack -PackId $GoodPackId -Version "0.0.2" -ReleaseDir $GoodFeed
    $GoodAppRoot = Install-SquirrelPackage -PackId $GoodPackId -ReleaseDir $NoUpdateFeed

    $CorruptFeed = Join-Path $TestRoot "corrupt-feed"
    $CorruptBaseFeed = Join-Path $TestRoot "corrupt-base-feed"
    $CorruptPackId = "DeepAnalysisAgentE2ECorrupt"
    Invoke-SquirrelPack -PackId $CorruptPackId -Version "0.0.1" -ReleaseDir $CorruptFeed
    Copy-Item -Recurse -Path $CorruptFeed -Destination $CorruptBaseFeed
    Invoke-SquirrelPack -PackId $CorruptPackId -Version "0.0.2" -ReleaseDir $CorruptFeed
    $CorruptPackage = Get-ChildItem $CorruptFeed -Filter "*-0.0.2-full.nupkg" | Select-Object -First 1
    if ($null -eq $CorruptPackage) {
        throw "Target package was not created in $CorruptFeed"
    }
    $Stream = [System.IO.File]::Open(
        $CorruptPackage.FullName,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite
    )
    try {
        $null = $Stream.Seek(0, [System.IO.SeekOrigin]::End)
        $Stream.WriteByte(0)
    } finally {
        $Stream.Dispose()
    }
    $CorruptAppRoot = Install-SquirrelPackage `
        -PackId $CorruptPackId -ReleaseDir $CorruptBaseFeed

    $StallAppRoot = Join-Path $LocalAppData "DeepAnalysisAgentE2EStall"
    $StallAppDir = Join-Path $StallAppRoot "app-0.0.1"
    New-Item -ItemType Directory -Force -Path $StallAppDir | Out-Null
    Copy-Item (Join-Path $Payload "DeepAnalysisAgent.exe") $StallAppDir
    New-StalledUpdateExe -OutputPath (Join-Path $StallAppRoot "Update.exe")

    $env:DAA_E2E_GOOD_APP_ROOT = $GoodAppRoot
    $env:DAA_E2E_GOOD_FEED = $GoodFeed
    $env:DAA_E2E_NO_UPDATE_FEED = $NoUpdateFeed
    $env:DAA_E2E_CORRUPT_APP_ROOT = $CorruptAppRoot
    $env:DAA_E2E_CORRUPT_FEED = $CorruptFeed
    $env:DAA_E2E_STALL_APP_ROOT = $StallAppRoot

    Push-Location $RepoRoot
    try {
        uv run pytest tests/windows/test_updater_e2e.py -v
        if ($LASTEXITCODE -ne 0) {
            throw "Windows updater end-to-end tests failed"
        }
    } finally {
        Pop-Location
    }
} finally {
    Set-ItemProperty -Path $ShellFolders -Name "Local AppData" -Value $OriginalLocalAppData
}
