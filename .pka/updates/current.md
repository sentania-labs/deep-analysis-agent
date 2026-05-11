# PKA Updates — Deep Analysis Agent

Rolling session log. Most recent entry first.

## 2026-05-10 — v0.4.5 file filter + client_version fix

**Type:** fix

Two bug fixes shipped together. (1) Watcher now filters by filename glob in addition to suffix: new `MTGOSettings.watched_name_glob` (defaults to `"Match_GameLog_*.dat"`) is threaded into `LogWatcher`'s `_startup_scan` and `_Handler._maybe` via `fnmatch`, so `GChat.dat`, `IdentityV2.dat`, GoatBot, and appinfo noise are no longer uploaded. (2) `auth.register_with_credentials()` now takes a required `client_version` parameter and sends it in the request body, fixing the 422 from `POST /auth/agent/register-with-credentials`. Refactored `CLIENT_VERSION` constant in `first_run.py` out in favor of importing `__version__` from the package (also applied in `main.py` + `test_startup_banner.py`) — single source of truth. New tests: `test_register_with_credentials_sends_client_version` inspects respx's recorded request body; `test_matching_name_fires` / `test_non_matching_name_ignored` cover the watcher glob with the real filenames from the field (`Match_GameLog_20240501_123456.dat`, `GChat.dat`, `IdentityV2.dat`). Version 0.4.4 → 0.4.5 in `pyproject.toml` and `__init__.__version__`. Local gates green: pytest 78 passed/1 skipped, ruff + mypy clean.

## 2026-05-10 21:55 UTC — dual-registration v0.4.4

**Type:** feature

Added a second registration path so users can sign in with email + password instead of pasting a one-shot registration code. New `auth.register_with_credentials()` calls `POST /auth/agent/register-with-credentials`, maps the server's `agent_key` to `RegistrationResult.api_token`, and translates the documented status codes (401 → bad creds, 403 → admin blocked, 409 → rate / already-registered) into `RegistrationError` messages. `first_run.run_first_run_flow()` now opens with a method picker (tk simpledialog or stdin) — option 1 prompts for email/password (password masked via `show="*"` or `getpass`) plus an agent-name override (defaults to hostname) and registers in one shot; option 2 keeps the existing 3-attempt code loop unchanged. Five respx tests cover the new auth path (success + 401/403/409 + network error). Version bumped 0.4.3 → 0.4.4 across `pyproject.toml`, `__init__.__version__`, `first_run.CLIENT_VERSION`, with a CHANGELOG entry. Local gates green: `ruff check` + `ruff format --check` + `mypy src/` clean; pytest 75 passed, 1 skipped (DPAPI on non-Windows, expected). Self-review approved at commit `459e01c` after a first round flagged an unformatted test body. PR #11 opened on `feat/dual-registration`.
