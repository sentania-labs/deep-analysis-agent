# Changelog

## Unreleased

### What's new
- **Stability gate + finalized detection** — `mtgo.stability_seconds` default raised to 600s to align with MTGO's match timeout, eliminating intermediate snapshots of in-progress matches. Once a match log goes stable, the agent tail-scans for `wins the match` / `has conceded from the match`; if no signal is found, the file ships anyway tagged `agent_classification=inconclusive` so the server's holding pen can decide what to do with it.
- **Autostart on Windows login** — agent registers itself under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` on first launch so it starts with Windows. A "Start with Windows" toggle in the tray menu lets users opt out; the choice persists across launches. Squirrel uninstall removes the Run-key entry (best-effort, dormant until the EXE is packed Squirrel-aware).

### Fixes
- **Autostart no longer pins the old version after an update**: the Windows Run key now stores Squirrel's stable `Update.exe --processStart DeepAnalysisAgent.exe` entry point instead of the versioned `app-<version>\DeepAnalysisAgent.exe` path, which Squirrel replaces on update. Run keys already written in the old form are rewritten on startup, so an affected user needs one manual launch (Start Menu shortcut) to pick the fix up.

## v0.4.10

### What's new
- **Check for Updates actually checks** — the tray menu item now runs a real Squirrel update check in the background and reports the result via notification, instead of dismissing with "updates are checked at startup."
- **Pause Sync** — new tray menu toggle to pause/resume file watching and upload without quitting the agent. Files created while paused are picked up on resume.
- **Bulk startup sync** — startup scan now does a single bulk comparison of the log directory against the dedup DB, only queuing files that are new or changed. Eliminates per-file DB lookups on startup for already-uploaded files.

## v0.4.7 — 2026-05-10

### Fixes
- **register-with-credentials KeyError** — agent now reads `api_token` (the actual server field) instead of the non-existent `agent_key`, and parses `user_id` from the response instead of hardcoding `0`. This matches the response shape of the code-based `register()` flow.

## v0.4.5 — 2026-05-10

### Fixes
- **File filter** — watcher now only uploads `Match_GameLog_*.dat` files; chat logs, identity files, and other `.dat` noise are ignored. Configurable via `mtgo.watched_name_glob`.
- **register-with-credentials 422** — `client_version` is now sent in the request body, matching the server schema.

## v0.4.4 — 2026-05-10

### What's new
- **Dual registration methods** — on first launch, the agent now offers two registration paths: log in with email/password (new `POST /auth/agent/register-with-credentials` endpoint) or enter a registration code (existing flow). Agent name defaults to hostname; user may override at prompt.

## v0.4.3 — 2026-04-26

### What's new

- **About window close** (#1) — AboutWindow is now a proper threaded sub-window with working close/re-open, managed via a sub-window registry.
- **Startup version banner** (#2) — Prominent version/config-path banner on agent startup for easier diagnostics.
- **In-app Log Viewer** (#3) — LogViewerWindow: live-tailing log viewer accessible from tray menu, with level filter (DEBUG/INFO/WARNING/ERROR), copy-to-clipboard, and save-to-file.
- **Settings window with hot-reload** (#4) — SettingsWindow lets users edit server URL, auth, log level, and MTGO path without restarting the agent. Config changes apply immediately via reload_config().
- **Manalog-style log renderer** (#5) — Plaintext structlog renderer styled after manalog's output for readable console/file logs.

## v0.4.2 — 2026-04-26

Initial release of the Deep Analysis agent (Windows tray client). First-run MTGO directory detection, config migration for stale Default paths, Squirrel.Windows packaging scaffolding.
