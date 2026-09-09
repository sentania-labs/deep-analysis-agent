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

The `build-windows` CI job builds a frozen fixture executable, packages and
installs it with Clowd.Squirrel, then runs
[`tests/windows/run_updater_e2e.ps1`](../tests/windows/run_updater_e2e.ps1).
The harness drives the installed executable against local no-update, good,
corrupt-package, and stalled-updater cases, including a repeat check after
installation and discovery of the stable `Update.exe`.

The internal `--updater-e2e --feed <local-directory> --output <json-file>` entry
runs the tray update worker headlessly, capturing notification bodies and runtime
identity in JSON with a sibling `.log` file. The job asserts these captures;
it does not display real Windows tray notifications. Both fixture packages use
the same frozen payload, so this checks installation state rather than launching
a newer application build. Mocked unit tests retain coverage of unexpected errors.

Run this harness only on a disposable Windows runner: it temporarily redirects
the user's Local AppData shell-folder registry value and installs test packages.
The script restores that registry value on exit.

Manual verification covers the real tray on an interactive Windows desktop.
To check the [update workflow](../README.md#installation) across two releases:

1. Install a release containing the updater changes via `Setup.exe`.
2. Publish a newer release to the update feed.
3. Select **Check for Updates** from the installed agent and wait for the result.
4. After success, quit and launch from the Start Menu, then confirm via
   tray → About that the version number changed.

## Version format

Versions follow `vMAJOR.MINOR.PATCH`. The `v` prefix is the git tag format;
the NuGet package version strips the `v` (e.g. tag `v0.4.0` → package `0.4.0`).
