# Changelog

## v0.4.3 — 2026-04-26

### What's new

- **About window close** (#1) — AboutWindow is now a proper threaded sub-window with working close/re-open, managed via a sub-window registry.
- **Startup version banner** (#2) — Prominent version/config-path banner on agent startup for easier diagnostics.
- **In-app Log Viewer** (#3) — LogViewerWindow: live-tailing log viewer accessible from tray menu, with level filter (DEBUG/INFO/WARNING/ERROR), copy-to-clipboard, and save-to-file.
- **Settings window with hot-reload** (#4) — SettingsWindow lets users edit server URL, auth, log level, and MTGO path without restarting the agent. Config changes apply immediately via reload_config().
- **Manalog-style log renderer** (#5) — Plaintext structlog renderer styled after manalog's output for readable console/file logs.

## v0.4.2 — 2026-04-26

Initial release of the Deep Analysis agent (Windows tray client). First-run MTGO directory detection, config migration for stale Default paths, Squirrel.Windows packaging scaffolding.
