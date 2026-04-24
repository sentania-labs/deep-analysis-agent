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

> **Squirrel.Windows installer — coming in W8c.**

The installer will be published as a GitHub Release asset. Download, run, done — it installs per-user to `%LOCALAPPDATA%\DeepAnalysis\` with no administrator privileges required.

## First-run registration

On first launch the agent prompts you for a registration code (`XXXX-XXXX`).

1. Log into the Deep Analysis web UI and mint a code under **Settings → Agents → New registration code**. Codes are valid for 10 minutes and can only be used once.
2. Paste the code into the agent's dialog.
3. The agent exchanges it with the server for a long-lived `api_token`, saves it (DPAPI-encrypted on Windows) to `%LOCALAPPDATA%\DeepAnalysis\config.toml`, and begins watching your MTGO log directory.

Right-click the tray icon for **Settings**, **Open logs folder**, or **Re-register...** (to swap registration to a different user / rotate the token).

## Normal operation

The agent is tray-resident — the icon sits in your system tray:

- **Colorless (C) mana pip** — idle, no upload in flight.
- **Cycling WUBRG** — currently uploading a file to the server.
- **Red** — error (last upload failed, or the token has been revoked).

Every 5 minutes the agent heartbeats the server so your account dashboard shows the agent as live. If an administrator revokes the agent's token, the next heartbeat surfaces it as an error state and uploads stop until you re-register.

## Troubleshooting

- **Revoked token** — tray turns red and uploads stop. Mint a new registration code and use **Tray → Re-register...**.
- **Server unreachable** — uploads retry once on transient 5xx/network errors. Persistent failures leave the file on disk; the watcher picks it up again on the next launch or directory change.
- **Logs** — structured JSON logs live under `%LOCALAPPDATA%\DeepAnalysis\logs\`. **Tray → Open logs folder** jumps straight there.
- **Config** — `%LOCALAPPDATA%\DeepAnalysis\config.toml`. The `api_token` is never stored in plaintext on Windows; only the DPAPI-encrypted `api_token_enc` field is written.

See [`docs/auth-flow.md`](docs/auth-flow.md) for full details of the registration + heartbeat protocol.

## Requirements

- Windows 10 or later (x64)
- A running [Deep Analysis server](https://github.com/sentania-labs/deep-analysis-server)

## Server repo

The server-side stack (6 open-source services, Docker Compose, Alembic migrations, web UI) lives at:

> https://github.com/sentania-labs/deep-analysis-server

## License

MIT — see [LICENSE](LICENSE).
