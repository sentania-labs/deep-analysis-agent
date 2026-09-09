# Settings reference

Deep Analysis stores its settings in
`%LOCALAPPDATA%\DeepAnalysis\config.toml`. The Settings window is the
operator interface for every runtime setting. Registration identity and
credentials are managed by the agent and are shown here only to make their
ownership explicit.

## Persisted settings audit

| Setting | Classification | Settings control | Operational effect |
| --- | --- | --- | --- |
| `server.url` | Operator-editable | Server URL | Destination for registration, heartbeat, and uploads. |
| `server.tls_verify` | Operator-editable | Verify TLS certificate and Custom CA bundle | Uses the HTTP client's default CA trust, a selected CA bundle, or disables verification. |
| `agent.machine_name` | Operator-editable | Machine name | Operator-readable identity sent during registration. |
| `agent.agent_id` | Derived | Read-only Agent ID | Assigned by the server during registration. |
| `agent.api_token` | Internal | No editable control | Issued by the server and stored as DPAPI-encrypted `api_token_enc` on Windows. |
| `agent.registered_at` | Derived | No editable control | Timestamp recorded by the agent after successful registration. |
| `agent.heartbeat_interval_seconds` | Operator-editable | Heartbeat interval | Delay between server heartbeats. |
| `mtgo.log_dir` | Operator-editable | Log directory | Root searched for MTGO match logs. |
| `mtgo.watched_suffixes` | Operator-editable | Advanced MTGO, Watched suffixes | Fast file-type filter applied before filename patterns. |
| `mtgo.watched_name_globs` | Operator-editable | Advanced MTGO, Watched name globs | Filename patterns that select files for upload. |
| `mtgo.stability_seconds` | Operator-editable | Advanced MTGO, Stability wait | Minimum unchanged period before a match log is uploaded. See input rules below. |
| `mtgo.card_data_source_dir` | Operator-editable | Advanced MTGO, CardDataSource directory | Directory containing MTGO card catalog XML files. |
| `mtgo.card_data_source_enabled` | Operator-editable | Advanced MTGO, Upload MTGO card data | Enables or disables card catalog uploads. |
| `logging.level` | Operator-editable | Logging level | Minimum severity written to the agent log. |
| `logging.log_dir` | Operator-editable | Logging directory | Overrides the default agent log location. Blank uses the application log directory. |
| `logging.stderr` | Operator-editable | Also log to stderr | Mirrors log output to standard error for diagnostics. |
| `logging.format` | Operator-editable | Logging format | Selects human-readable plaintext or JSON records. |

`mtgo.watched_name_glob` is a legacy migration input, excluded from persisted
output. When loaded, its value is moved into `mtgo.watched_name_globs` and the
legacy field is cleared. Start with Windows is also visible in Settings, but it
is registry-backed and is not part of the persisted settings models.

## Advanced MTGO input rules

- Enter suffixes and filename globs one per line. Blank lines are ignored.
- At least one suffix and one filename glob are required.
- Stability wait cannot be lower than 600 seconds.
- When card data upload is enabled, use auto-detection or select a
  CardDataSource directory.
- Disabling card data upload disables its directory controls. An existing
  directory value remains available if uploads are enabled again.

![Advanced MTGO settings on Linux test display](screenshots/advanced-mtgo-settings.png)

CardDataSource enable state and directory changes apply after the agent restarts.
Saving either change keeps Settings open with an inline restart notice.

## Logging and TLS validation

In Settings, the Logging section controls log format and destination. A blank
logging directory uses `%LOCALAPPDATA%\DeepAnalysis\logs\`; records are written
to `agent.log`. Choose plaintext or JSON with Logging format.

Save checks that `agent.log` can be opened for appending, creating the directory
and an empty log file if needed. If the check fails, Settings shows an inline
error and retains the previously saved configuration.

With Verify TLS certificate enabled, leave Custom CA bundle blank to use the
HTTP client's default CA trust, or select a PEM CA bundle. Save checks the bundle
by loading it into an SSL context. An unreadable or invalid bundle produces an
inline error without saving the configuration. With verification disabled, the
bundle field is ignored.

## PR handoff

Follow-up for firstmate to file as an issue: apply CardDataSource changes without
restart. Include this follow-up in the PR body. Background-task lifecycle handling
on reload is deferred from this change.
