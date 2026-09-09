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

For the user workflow and notifications, see [Updates](../README.md#installation).
The tray worker calls `updater.check_for_update()`, then `apply_update()` only
when Squirrel reports releases to apply and a nonempty target version.

1. `Update.exe --checkForUpdate` checks the GitHub latest-release feed with a
   30-second timeout. The agent reads the final JSON object after progress lines,
   using `releasesToApply` and `futureVersion`.
2. `Update.exe --update` applies the release. The agent waits for at most the
   fixed 120-second timeout; timing out does not terminate the updater.
3. Success requires exit code zero and, when a target version was supplied,
   an `app-<target_version>` directory with no `.not-finished` marker. Starting
   the process alone is not success. This verifies installation state, not a
   successful launch of the new build.
4. Restart through the stable Squirrel entry point to run the installed version.
   Squirrel manages cleanup of old version directories.

Updater and autostart discovery share `paths.squirrel_update_exe()`;
`updater._find_update_exe()` is a compatibility alias.

## Autostart and the stable entry point

Because the running exe lives inside a versioned `app-<version>` directory
that Squirrel can clean up, nothing that must survive an update may record that
path. The Windows Run key therefore stores the Squirrel entry point:

```text
%LOCALAPPDATA%\DeepAnalysisAgent\Update.exe --processStart DeepAnalysisAgent.exe
```

`Update.exe` sits alongside the `app-*` directories rather than inside one,
and always starts the newest installed version. Builds before this change
wrote the versioned exe path directly, so login kept launching the
pre-update build; the agent rewrites any such value on startup
(`autostart.migrate_stale_command`). That rewrite only runs once the fixed
build actually starts, so a user whose stale Run key points at an
already-cleaned-up `app-*` directory must launch from the Start Menu once.

## Squirrel hooks

The agent handles Squirrel's lifecycle hooks in `main.py`:
- `--squirrel-install` — no-op (Squirrel handles shortcut creation)
- `--squirrel-updated` — no-op for v0.4.0 (future: trigger re-registration prompt)
- `--squirrel-obsolete` — no-op (old version being retired)
- `--squirrel-uninstall` — no-op (Squirrel handles shortcut removal)

All hooks exit 0 immediately so Squirrel's own logic proceeds unimpeded.
