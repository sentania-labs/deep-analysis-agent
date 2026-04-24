# Release Process

## Cutting a release

1. Ensure `main` is green (all CI checks pass).
2. Tag the release: `git tag v0.4.0 && git push --tags`
3. The `release.yml` GitHub Actions workflow fires on the tag.
4. It builds the PyInstaller bundle on `windows-latest`, packages via Squirrel, and creates a GitHub Release with:
   - `Setup.exe` — the installer (runs silently, no UAC)
   - `Setup.msi` — MSI alternative (same content)
   - `RELEASES` — Squirrel's update-check manifest
   - `DeepAnalysisAgent-<version>-full.nupkg` — the full package (for Squirrel's --releasify)

## Verifying the update path

To smoke-test auto-update across two versions:
1. Install v0.4.0 via `Setup.exe`.
2. Tag and release v0.4.1.
3. Restart the agent — it should auto-update within one startup cycle.
4. Confirm via tray → About that the version number changed.

## Version format

Versions follow `vMAJOR.MINOR.PATCH`. The `v` prefix is the git tag format;
the NuGet package version strips the `v` (e.g. tag `v0.4.0` → package `0.4.0`).
