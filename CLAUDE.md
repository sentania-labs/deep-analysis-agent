# CLAUDE.md — Deep Analysis Agent

MIT-licensed Windows tray client for the Deep Analysis MTGO match analytics platform.

**Plan reference:** `/home/scott/.claude/plans/steady-dazzling-charm.md` (Deep Analysis v0.4.0 — Greenfield v1 Launch, approved 2026-04-23)

This is a greenfield repo. Nothing is ported wholesale from manalog 0.3.x — read that codebase for patterns and learnings only.

## What this is

The agent is the client-side half of the Deep Analysis platform. It runs as a Windows system tray resident, watches the MTGO log directory for new game log files, and ships them to a Deep Analysis server over HTTPS. The server does the parsing, analytics, and AI coaching.

- **License:** MIT (open-source, maximally permissive)
- **Platform:** Windows only for v1. Cross-platform is not in scope.
- **Packaging:** Squirrel.Windows (per-user install, invisible auto-updates, no UAC prompts)
- **Install target:** `%LOCALAPPDATA%\DeepAnalysis\`

## Tech stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.12+ |
| Tray service | pystray |
| File watching | watchdog |
| HTTP client | httpx (async) |
| Config | Pydantic v2 (BaseSettings, TOML config file) |
| Logging | Python structlog (JSON formatter) |
| Packaging | PyInstaller (single-file exe) |
| Distribution / self-update | Squirrel.Windows (NuGet-based, per-user, invisible) |
| Server client types | OpenAPI-generated from deep-analysis-server repo |

## Design decisions — do not change without discussion

### Squirrel.Windows packaging

Per-user install to `%LOCALAPPDATA%\DeepAnalysis\`. Squirrel handles auto-updates natively — the updater installs alongside the app and applies updates on next launch with no UAC prompts and no interruption to the user. This replaces the fragile self-update mechanism in manalog 0.3.x (which ran from temp, didn't replace the installed exe, and didn't kill the parent process cleanly). Do NOT switch to MSI-to-Program-Files or WiX. Squirrel is the decision.

### OpenAPI-generated client types

The `deep-analysis-server` repo is the source of truth for all API contracts. The agent consumes generated Python types from `openapi/generated/` — this directory is populated by CI from the server's OpenAPI spec. Never hand-write types for server-side models. If a server model changes, regenerate; don't patch by hand.

### Tray-centric UX

The agent is a tray service, not a windowed app. The tray icon is the primary user-visible surface:

- **Idle:** colorless (C) mana pip
- **Uploading:** icon cycles through WUBRG mana pips (W → U → B → R → G)
- **Error/disconnected:** red indicator (TBD)
- Right-click context menu: Settings, Check for updates, About, Quit

This UX was validated in manalog v0.3.7/v0.3.8. Keep it.

### No code copied wholesale from manalog 0.3.x

Read the 0.3.x codebase for patterns and learnings. Do not paste blocks of code. Write fresh.

Key conceptual keepers from 0.3.x (read these files in `workspaces/manalog/`, don't copy):
- `agent/raw_shipper.py` — file-stability check before upload + SHA-256 dedup ordering. The v0.3.7 fix (stability check before dedup, not after) is a keeper.
- `agent/tray.py` — icon-cycling approach and threading model (pystray event loop + watchdog thread)
- `agent/generate_icons.py` — icon generation pattern (WUBRG identity pie + mana pip icons + C idle)

### Icons

Five WUBRG mana pip icons + one colorless (C) idle icon + one identity-pie icon (all five colors, wedge-style). Generated via `icons/generate_icons.py` (to be written). Target files:

```
icons/W.ico
icons/U.ico
icons/B.ico
icons/R.ico
icons/G.ico
icons/C.ico
icons/identity.ico
```

The `generate_icons.py` script produces these from code (no static PNG assets checked in). Read the manalog equivalent for the generation approach.

### Windows-only for v1

Cross-platform is explicitly out of scope. Don't add platform guards, shims, or macOS/Linux paths. If a dependency is Windows-only, that's fine.

## Development guidelines

- **Type hints everywhere.** No untyped function signatures.
- **Pydantic v2 for config.** `BaseSettings` backed by a TOML config file at `%LOCALAPPDATA%\DeepAnalysis\config.toml`. Environment variable overrides for testing.
- **Structured logging.** Use `structlog` with JSON formatter. Log level configurable via config.
- **Terse naming conventions.** Short, clear names. No Hungarian notation, no excessive prefixes.
- **Tests in `tests/`.** Unit tests for pure logic (dedup, config parsing, stability checks). Integration tests are optional and not required pre-ship for v0.4.0.
- **Code review protocol:** for non-trivial changes, spawn a subagent to self-review before committing.

## Project structure

```
deep-analysis-agent/
├── src/
│   └── deep_analysis_agent/   # main Python package
│       └── __init__.py
├── installer/                  # Squirrel.Windows packaging config
│   └── README.md              # explains intent + deferred to Phase 3
├── openapi/
│   └── generated/             # CI-populated from server OpenAPI spec
│       └── README.md
├── icons/                      # ICO artwork (generate_icons.py populates this)
│   └── README.md
├── tests/                      # unit + integration tests
│   └── .gitkeep
├── .github/
│   └── workflows/             # CI (added in Phase 3)
├── .pka/
│   └── updates/
│       └── current.md         # rolling PKA update log
├── pyproject.toml
├── .gitignore
├── README.md
├── CLAUDE.md                  # this file
└── LICENSE                    # MIT
```

## Phase context (as of initial scaffolding)

This is **Phase 1 — Foundation**. The repo exists with correct license and scaffolding. No agent code yet. Phase 3 is when agent code is written.

See the plan for phase sequencing: server (Phase 2) before agent code (Phase 3).

## PKA integration

- Status marker: `agents/riker/status/deep-analysis-agent.md` in the PKA repo
- Delegation: full delegation (matches manalog posture per Scott's memory)
- Updates: write session summaries to `.pka/updates/current.md` per the pka-workspace-updates skill
