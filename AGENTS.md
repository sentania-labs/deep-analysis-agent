# AGENTS.md: Deep Analysis Agent

MIT-licensed Windows tray client for the Deep Analysis MTGO match analytics platform.

Nothing is ported wholesale from manalog 0.3.x. Read that codebase for patterns and learnings only.

## What this is

The agent is the client-side half of the Deep Analysis platform. It runs as a Windows system tray resident, watches the MTGO log directory for new game log files, and ships them to a Deep Analysis server over HTTPS. The server does the parsing, analytics, and AI coaching.

- **License:** MIT (open-source, maximally permissive)
- **Platform:** Windows only for v1. Cross-platform is not in scope.
- **Packaging:** Squirrel.Windows (see [installer architecture](docs/installer-architecture.md))
- **Install target:** see [Installation](README.md#installation)

## Charter

This workspace is software. The "What this is" / product
scope above is the charter. Software authors don't touch
infrastructure outside their charter, even with credentials
available. For work that needs out-of-charter access, use a
sanctioned cross-system channel.

## Tech stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.12+ |
| Tray service | pystray |
| File watching | watchdog |
| HTTP client | httpx (async) |
| Config | Pydantic v2 (BaseSettings, TOML config file) |
| Logging | Python structlog |
| Packaging | PyInstaller (single-file exe) |
| Distribution / self-update | Squirrel.Windows (see [update flow](docs/installer-architecture.md#update-flow)) |
| Server client types | OpenAPI-generated from deep-analysis-server repo |

## Design decisions: do not change without discussion

### Squirrel.Windows packaging

Squirrel.Windows is the packaging decision. Do NOT switch to MSI-to-Program-Files
or WiX. See [installer architecture](docs/installer-architecture.md) for the
installation and update contract, and [README](README.md#installation) for usage.

### OpenAPI-generated client types

The `deep-analysis-server` repo is the source of truth for all API contracts. The agent consumes generated Python types from `openapi/generated/`. This directory is populated by CI from the server's OpenAPI spec. Never hand-write types for server-side models. If a server model changes, regenerate; don't patch by hand.

### Tray-centric UX

The agent is a tray service, not a windowed app. The tray icon is the primary user-visible surface:

- **Idle:** colorless (C) mana pip
- **Uploading:** icon cycles through WUBRG mana pips (W to U to B to R to G)
- **Error/disconnected:** red indicator (TBD)
- Right-click context menu: Settings, Check for updates, About, Quit

This UX was validated in manalog v0.3.7/v0.3.8. Keep it.

### No code copied wholesale from manalog 0.3.x

Read the 0.3.x codebase for patterns and learnings. Do not paste blocks of code. Write fresh.

Key conceptual keepers from 0.3.x (read these files in `workspaces/manalog/`, don't copy):
- `agent/raw_shipper.py`: file-stability check before upload + SHA-256 dedup ordering. The v0.3.7 fix (stability check before dedup, not after) is a keeper.
- `agent/tray.py`: icon-cycling approach and threading model (pystray event loop + watchdog thread)
- `agent/generate_icons.py`: icon generation pattern (WUBRG identity pie + mana pip icons + C idle)

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
- **Structured logging.** Use `structlog`; operator controls are documented in the [settings reference](docs/settings-reference.md#logging-and-tls-validation).
- **Terse naming conventions.** Short, clear names. No Hungarian notation, no excessive prefixes.
- **Tests in `tests/`.** Unit tests for pure logic (dedup, config parsing, stability checks). Integration tests are optional and not required pre-ship for v0.4.0.
- **Code review protocol:** for non-trivial changes, spawn a subagent to self-review before committing.
- **PR discipline:** see [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and required checks, and [release verification](docs/release-process.md#verifying-the-update-path) for Windows updater coverage.
- **Releases are tag-based.** To cut a release, merge work to `main` via PR (CI green), then `git tag vX.Y.Z && git push origin vX.Y.Z` from `main`. The release workflow builds the PyInstaller binary, packages with Squirrel, and creates a GitHub Release. The version is injected from the tag into `__init__.py` at build time. No version-bump commit is required. The tag is the source of truth.

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
├── AGENTS.md                  # project guidance
├── CLAUDE.md                  # imports AGENTS.md
└── LICENSE                    # MIT
```

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
