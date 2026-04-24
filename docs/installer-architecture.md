# Installer Architecture

## Overview

```
Python source
     │
     ▼
 PyInstaller          Produces a one-folder bundle:
 (build step)         dist/deep-analysis-agent/
                          DeepAnalysisAgent.exe
                          *.dll / *.pyd
                          icons/
     │
     ▼
 NuGet pack           Wraps the folder into a NuGet package:
 (nuget CLI)          DeepAnalysisAgent-<version>.nupkg
     │
     ▼
 Squirrel             Produces the release directory:
 --releasify          Releases/
                          Setup.exe          (bootstrapper, ~1MB)
                          Setup.msi          (MSI wrapper)
                          RELEASES           (update manifest)
                          *-full.nupkg       (full package)
                          *-delta.nupkg      (delta, subsequent releases)
```

## Install flow (end-user)

1. User downloads `Setup.exe`.
2. Squirrel's bootstrapper extracts to `%LOCALAPPDATA%\DeepAnalysisAgent\`.
3. Squirrel creates a Start Menu shortcut and runs `DeepAnalysisAgent.exe --squirrel-install`.
4. The agent exits 0 (no-op for v0.4.0) and Squirrel completes the install.
5. Squirrel launches the agent normally.

## Update flow

On each launch, the agent's embedded `Update.exe` checks the GitHub Release `RELEASES` file against the local version. If a newer version exists:
1. Download the delta NuGet package.
2. Extract to a new versioned app directory under `%LOCALAPPDATA%\DeepAnalysisAgent\`.
3. On next launch, Update.exe swaps to the new version.
4. The old version directory is cleaned up.

## Squirrel hooks

The agent handles Squirrel's lifecycle hooks in `main.py`:
- `--squirrel-install` — no-op (Squirrel handles shortcut creation)
- `--squirrel-updated` — no-op for v0.4.0 (future: trigger re-registration prompt)
- `--squirrel-obsolete` — no-op (old version being retired)
- `--squirrel-uninstall` — no-op (Squirrel handles shortcut removal)

All hooks exit 0 immediately so Squirrel's own logic proceeds unimpeded.
