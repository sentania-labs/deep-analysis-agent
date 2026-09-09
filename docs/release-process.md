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

To smoke-test the [update workflow](../README.md#installation) across two versions:

1. Install a release containing the updater changes via `Setup.exe`.
2. Publish a newer release to the update feed.
3. Select **Check for Updates** from the installed agent and wait for the result.
4. After success, quit and launch from the Start Menu, then confirm via
   tray → About that the version number changed.

## Version format

Versions follow `vMAJOR.MINOR.PATCH`. The `v` prefix is the git tag format;
the NuGet package version strips the `v` (e.g. tag `v0.4.0` → package `0.4.0`).
