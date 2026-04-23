# installer/

Squirrel.Windows packaging configuration for Deep Analysis Agent.

## Intent

This directory will hold the NuGet spec and Squirrel build configuration for the per-user Windows installer. The build pipeline (Phase 3) will:

1. PyInstaller builds a single-file `DeepAnalysisAgent.exe`
2. NuGet spec packages the exe + assets into a `.nupkg`
3. Squirrel's `Releasify` produces a `Releases/` directory with:
   - `Setup.exe` (bootstrapper)
   - `RELEASES` manifest
   - Delta NuPkg files for incremental updates
4. GitHub Release asset: `DeepAnalysisAgent-<version>-Setup.exe`

## Self-update flow

Squirrel installs to `%LOCALAPPDATA%\DeepAnalysis\` (per-user, no UAC). At next launch after a new GitHub Release, Squirrel's `UpdateManager` fetches the `RELEASES` manifest, downloads the delta package, and applies the update. The old process is replaced cleanly — no temp-dir issues, no manual restart logic needed in the Python code.

## Status

Deferred to Phase 3. No packaging config here yet.

## Reference

- [Squirrel.Windows](https://github.com/Squirrel/Squirrel.Windows)
- manalog 0.3.x used WiX + MSI (`installer/manalog.wxs`) — that approach is retired; Squirrel replaces it.
