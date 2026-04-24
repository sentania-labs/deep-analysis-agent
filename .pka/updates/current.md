# PKA Updates — Deep Analysis Agent

Rolling session log. Most recent entry first.

---

## 2026-04-24 — v0.4.0 released (`0a09572`, `ea9e727`)

Follow-up to the Chocolatey→NuGet Squirrel swap. Two sequential fixes
to the release pipeline, both root-caused from run logs.

**Fix 1 (`0a09572`)** — Clowd.Squirrel 2.11.1 releasify rejected the
package: `There are no SquirreAwareApp's in the provided package`
(SquirrelCli/Program.cs:221). PyInstaller's bootloader is not a .NET
assembly and carries no SquirrelAwareVersion manifest. Added the
documented `--allowUnaware` flag to `Squirrel.exe pack`. Trade-off: the
four `main.py` lifecycle hooks (`--squirrel-install/updated/obsolete/
uninstall`) become dormant — Start Menu shortcut is still created, and
updates still apply on next launch. Acceptable for v1. Also added a
post-pack artifact verification step (Setup.exe + RELEASES + `*-full.nupkg`,
fail-fast) per the code-review protocol.

**Fix 2 (`ea9e727`)** — Squirrel pack then succeeded, but my own verify
step caught a filename mismatch: Clowd.Squirrel writes the setup bundle
as `<packId>Setup.exe` (Program.cs:370) — i.e.
`DeepAnalysisAgentSetup.exe` — not plain `Setup.exe`. Both the PS1
verify step AND the `softprops/action-gh-release@v2` upload list were
referencing the wrong name. Updated both; tightened the nupkg glob to
`*-full.nupkg`.

v0.4.0 tag re-cut twice (safe — zero published consumers prior). Final
successful run: 24871090963 (1m43s). Release published with all three
expected assets. Unverified: actual install on a Windows host — Scott's
smoke test. Future: embed a Win32 `<squirrelAware>1</squirrelAware>`
manifest in the PyInstaller bootloader if missing `--squirrel-firstrun`
hook hurts onboarding UX.

---

## 2026-04-23 — Release fix: swap Squirrel.Windows → Clowd.Squirrel (`619cf27`)

v0.4.0 release run 24868572334 failed at `choco install squirrel-windows` — that Chocolatey package does not exist. Switched to Clowd.Squirrel 2.11.1 from NuGet (`nuget install Clowd.Squirrel -Version 2.11.1 -ExcludeVersion -OutputDirectory tools`). Its `Squirrel.exe pack --packId ... --packVersion ... --packDirectory ... --releaseDir ...` CLI replaces the `--releasify` + separate `nuget pack` + `.nuspec` dance, so deleted `build/windows/deep-analysis-agent.nuspec` and dropped `Setup.msi` from the upload list (Clowd.Squirrel supports `--msi` but v1 doesn't ship MSI). Update.exe CLI remains back-compat with old Squirrel so `main.py`'s four lifecycle hooks are untouched. Smoke CI on main: run 24870646297. Re-cut v0.4.0 tag → release run 24870651260 (in progress). Note: Clowd.Squirrel is now superseded by Velopack; V2 still maintained for bug fixes and was the minimal-change path.

---

## 2026-04-23 — W8c: Squirrel.Windows packaging + release pipeline (`73b372b`)

W8 workstream complete. Added PyInstaller one-folder spec (`build/windows/deep-analysis-agent.spec`), packaging scripts (`build_pyinstaller.ps1`, `create_squirrel_release.ps1`), version-templated `.nuspec`, and a tag-triggered `release.yml` (windows-latest, fork-gated, uploads `Setup.exe` / `Setup.msi` / `RELEASES` / `*.nupkg`). CI gained a `build-windows` smoke job that runs PyInstaller on windows-latest to catch spec rot. `main.py` handles all four Squirrel lifecycle hooks (`--squirrel-install/updated/obsolete/uninstall`) as exit-0 no-ops; 6 new tests cover them. Committed WUBRG pip PNGs + `app.ico` (needed for CI PyInstaller bundling; `.gitignore` updated). Added `CONTRIBUTING.md` documenting the PR-flip from v0.4.0 onward — this is the repo's last direct-to-main commit. Docs: `docs/release-process.md`, `docs/installer-architecture.md`, README Installation section. All 5 CI jobs green (run 24865681518). To cut v0.4.0: `git tag v0.4.0 && git push --tags`.

---

## 2026-04-22 — Initial scaffolding (Phase 1 foundation)

Phase 1 foundation complete. Repo created at `sentania-labs/deep-analysis-agent` (MIT license). Scaffolded: LICENSE, README, CLAUDE.md, .gitignore, pyproject.toml, directory stubs (src/, installer/, openapi/generated/, icons/, tests/, .github/workflows/). Tagged v0.0.1. No agent code yet — Phase 3 work.

---

## 2026-04-23 — W8a salvage — core agent scaffold landed (`4642cf6`)

Salvaged W8a from a dead `claude -p` session. Verified and landed the uncommitted work (9 source files, 3 test files + `__init__.py`, fork-gated CI workflow, vendored excalidraw renderer + `agent-lifecycle` diagram, `icons/generate_icons.py`, pyproject/gitignore/__init__ edits) as commit `4642cf6` on `main`.

Scope of what landed: `config.py` (Pydantic v2 settings + TOML), `logging.py` (structlog JSON + rotating file), `instance_lock.py` (Windows named mutex, no-op off-Windows), `watcher.py` (watchdog + stability gate, v0.3.7 stability-before-hash ordering preserved), `dedup.py` (SHA-256 + SQLite seen-set, hash-before-mark ordering), `tray.py` (pystray scaffold with WUBRG cycle, guarded imports), `main.py` (wires it all together with TODO(W8b) shipping stub), `paths.py` (LOCALAPPDATA helpers). Tests: 10/10 pass.

Salvage fixes applied: `ruff check --fix` (UP017 `datetime.UTC`, UP037 removed quoted self-ref), `ruff format` pass, added `/uv.lock` to `.gitignore` (root lockfile generated by verification `uv sync --dev`; CI uses `uv pip install -e ".[dev]"` instead, so not intended to ship). Platform-conditional imports (`pywin32`, `pystray`) were already correctly guarded by the prior session — tests + ruff pass on Linux CI.

TODO(W8b) markers already in place at `config.AgentSettings` (agent_id / api_token fields) and `main.on_file_ready` (HTTP shipping wire-up). Diagram re-rendered cleanly via `docs/diagrams/render.py`.

Next: W8b — auth flow (device registration, DPAPI-protected JWT refresh token) + Squirrel.Windows packaging.

---

## 2026-04-23 — W8b: auth flow + HTTP shipper + first-run

Landed the auth/shipping layer. Three new modules: `auth.py` (register + heartbeat against the `sentania-labs/deep-analysis-server` `5bf9296` endpoints), `shipper.py` (POST /ingest/upload with 1-shot 5xx retry; 409 treated as deduped), `first_run.py` (tkinter prompt w/ stdin fallback, 3 retries, saves via atomic TOML write). `config.py` gained `agent_id / api_token / registered_at / heartbeat_interval_seconds`, plus `save_config()`, DPAPI `encrypt_token / decrypt_token` (no-op off-Windows with loud warning), and a `api_token_enc` TOML key so plaintext never hits disk. `main.py` rewritten as `asyncio.run(_async_main())` — drives the first-run prompt before acquiring the instance lock, bridges the threaded watcher to the async file handler via `run_coroutine_threadsafe`, runs a heartbeat background task, and flips tray → red on `revoked=True`. Tray gained a `Re-register...` menu item + `Registered as <machine_name>` non-interactive status line.

Tests: 27 pass (1 DPAPI roundtrip skip on Linux). New suites: `test_auth.py` (respx-mocked register/heartbeat incl. 401 and network errors), `test_shipper.py` (success / dedup / 409 / 5xx-retry / 5xx-exhausts), `test_config_token.py` (DPAPI roundtrip on Windows, plaintext-fallback warning off-Windows, full save/load roundtrip), `test_main_flow.py` (skip-if-seen, mark-after-ship, no-mark-on-failure via AsyncMock). Added `respx>=0.21` to dev deps; `win32crypt` added to mypy `ignore_missing_imports` override.

Fix-forward on W8a CI failures: removed stale `# type: ignore` comments in `instance_lock.py` / `tray.py` that mypy flagged as unused (strict mode + `ignore_missing_imports` made them redundant). Trimmed unused `pystray.*` and `win32con` entries from the override list. Diagram updated to include the auth + heartbeat flow alongside the file lifecycle; PNG re-rendered.

Docs: README gained First-run / Normal operation / Troubleshooting sections. New `docs/auth-flow.md` mirrors the server's `agent-protocol.md` from the client's perspective (code format, DPAPI storage, revocation UX).

Out of scope (W8c): Squirrel.Windows packaging, `/ingest/upload` server endpoint (agent-side shipper ready; server side still placeholder at `5bf9296`).

## 2026-04-24 04:04 — v0.4.0 re-cut with launchable exe  [batch]

**Type:** status

Frozen `DeepAnalysisAgent.exe` crashed on launch because PyInstaller froze `main.py` as a raw script with no parent package, so every relative import (`from .config import ...` × 9) raised `ImportError` before logging fired. Fix: new `src/deep_analysis_agent/__main__.py` (absolute-imports `deep_analysis_agent.main`), PyInstaller spec now points at it, `--version` flag added to `main()`, and a non-bypassable smoke step in `build-windows` that launches the exe and asserts exit 0 (had to switch from `&` to `Start-Process -Wait -PassThru` because the exe is `console=False` and pwsh never populated `$LASTEXITCODE` for the detached GUI process). Commits `6c3be86`, `573fe2c`, `4c50ce4`. v0.4.0 tag/release deleted and re-cut at `4c50ce4`; release run 24871518494 succeeded with all three assets. Setup.exe SHA256 `06bb1bc64f92513dc6cf063975d8a422482db52804da7878010aeb5cb7509bcd` (36,000,392 bytes). Scott's Windows install-smoke still the remaining go/no-go; CI now guarantees the bundled exe starts.

## 2026-04-24 05:35 — v0.4.1 released  [batch]

**Type:** status

Cut v0.4.1 (commit `7389bfd`, tag `v0.4.1`, release run 24874028119). Four changes in one commit: (1) `MTGOSettings.log_dir` defaults via a `_default_mtgo_log_dir()` factory that reads `%LOCALAPPDATA%/Apps/2.0` with a `~/AppData/Local/Apps/2.0` fallback — was hardcoded to the Default-user profile; (2) `LogWatcher.start()` no longer `mkdir`s the MTGO dir, now logs `watch_dir_missing` and returns early with `self._worker = None`; added `started` property; `_async_main` flips the tray to "error" when watcher doesn't start but keeps the agent running so Settings is reachable; (3) ported the real WUBRG mana-pip + identity-wheel icon generator from `manalog/agent/icons/generate_icons.py` (same author, MIT) producing 7 ICOs directly — deleted `generate_app_ico.py` and all PNG assets; `tray._load_icon` + PyInstaller spec rewired to `.ico`; `app.ico = identity.ico`; (4) bumped `pyproject.toml` 0.4.0.dev0 → 0.4.1 and `first_run.CLIENT_VERSION` 0.4.0 → 0.4.1. Two new config tests cover LOCALAPPDATA + fallback paths. All 34 tests + ruff + mypy green locally and on CI. Release published with `DeepAnalysisAgentSetup.exe` + `DeepAnalysisAgent-0.4.1-full.nupkg` + `RELEASES` attached: https://github.com/sentania-labs/deep-analysis-agent/releases/tag/v0.4.1

## 2026-04-24 06:04 — v0.4.2 Session A — tray menu + startup banner + plaintext logs  [batch]

**Type:** status

Session A of the v0.4.2 split landed as commit `bec92e7`; CI run 24874851231 green. Tray menu rebuilt with dynamic "Status: …" line (refreshed on state changes via `icon.update_menu()`), Open Dashboard (`webbrowser.open(config.server.url)`), Open Log (direct file; falls back to logs dir if the log hasn't been created yet), Settings, Check for Updates (notify + log line with the "Squirrel auto-checks" note), About (tkinter messagebox with version / machine / agent_id / server / MIT © Scott R. Bowe), Quit. Added a fourth tray state `watcher_disabled` so the status line can distinguish missing-MTGO-dir from other errors; main.py now flips to it when the watcher fails to start. Structured `agent_start` banner extracted into `_log_startup_banner()` and called first-thing from `_async_main` with version, agent_id, config_path, log_path, server_url, and MTGO log_dir. New `logging.format` field (default `plaintext`) switches structlog's terminal renderer between `JSONRenderer` and `ConsoleRenderer(colors=False)`. Renamed `_CYCLE_SECONDS` → module-level `PIP_CYCLE_SECONDS_PER_COLOR = 2.0` (value unchanged — 10s WUBRG cycle). 6 new tests (5 format + 2 banner + 1 cadence smoke); 41 pass / 1 skip; ruff + mypy strict clean. Version NOT bumped — Session B (config migration + first-run MTGO detect + bump + release) owns that.
