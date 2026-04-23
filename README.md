# Deep Analysis Agent

Windows system tray client for the [Deep Analysis](https://github.com/sentania-labs/deep-analysis-server) MTGO match analytics platform.

The agent runs silently in your system tray, monitors your MTGO log directory, and streams game log files to your Deep Analysis server as matches complete. No manual export, no copy-paste — just play.

## What it does

- Watches your MTGO log directory for new `.dat` / `.log` files
- Detects match-complete events and ships raw log files to the server
- Deduplicates uploads by SHA-256 so retries are safe
- Self-updates silently via Squirrel.Windows (no UAC prompts, no manual installs)
- Tray icon cycles through WUBRG mana colors while uploading; returns to colorless (C) when idle

## Installation

> **Install via MSI — coming soon.**

The installer will be published as a GitHub Release asset. Download, run, done — it installs per-user to `%LOCALAPPDATA%\DeepAnalysis\` with no administrator privileges required.

After install, right-click the tray icon and choose **Settings** to point the agent at your server URL and configure your API token.

## Requirements

- Windows 10 or later (x64)
- A running [Deep Analysis server](https://github.com/sentania-labs/deep-analysis-server)

## Server repo

The server-side stack (6 open-source services, Docker Compose, Alembic migrations, web UI) lives at:

> https://github.com/sentania-labs/deep-analysis-server

## License

MIT — see [LICENSE](LICENSE).
