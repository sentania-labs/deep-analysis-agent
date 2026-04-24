# Agent auth flow — client-side

This document mirrors the server's [`docs/agent-protocol.md`](https://github.com/sentania-labs/deep-analysis-server/blob/main/docs/agent-protocol.md) from the agent's perspective.

## Lifecycle

```
 first launch  ────┐
                   │   (no api_token in config.toml)
                   ▼
          ┌────────────────────┐
          │  prompt user for   │
          │  registration code │
          │    (XXXX-XXXX)     │
          └─────────┬──────────┘
                    │
                    ▼
          POST /auth/agent/register
          { code, machine_name, client_version }
                    │
              ┌─────┴─────┐
          200 │           │ 401
              ▼           ▼
  { agent_id,         (bad / expired code —
    api_token,         retry or give up)
    user_id }
              │
              ▼
  save config.toml
  (api_token_enc = DPAPI(api_token))
              │
              ▼
        watcher + tray
              │
              │   every 5 min
              ▼
  POST /auth/agent/heartbeat
  Authorization: Bearer <api_token>
  { client_version }
              │
          ┌───┴────┐
       200 │      401
           ▼       ▼
  { status,     stop uploads;
    revoked:    tray → red;
    false }     prompt re-register
```

## Registration code format

- 8 alphanumeric characters, formatted `XXXX-XXXX` (e.g. `AB34-XY78`).
- Minted by a logged-in user from the Deep Analysis web UI.
- Single-use, 10-minute TTL. Two agents racing the same code → one wins (401 for the loser).
- No audit trail — codes are pure bearer capabilities until consumed.

## Storage

The agent writes its config to `%LOCALAPPDATA%\DeepAnalysis\config.toml`.

Sensitive fields:

- `agent.api_token_enc` — the long-lived API token, wrapped via Windows DPAPI (`CryptProtectData`) and base64-encoded. Only the logged-in Windows user who registered the agent can decrypt it. On a non-Windows development machine the field is written in plaintext with a loud log warning; **don't ship that build**.
- `agent.agent_id` — opaque server-assigned identifier. Not secret, but pair it with the token for support requests.

The raw `api_token` is held only in memory at runtime — it is never persisted to disk.

## Heartbeat

Every `agent.heartbeat_interval_seconds` (default 300), the agent posts:

```
POST /auth/agent/heartbeat
Authorization: Bearer <api_token>
{ "client_version": "0.4.0" }
```

Response shape:

```json
{ "status": "ok", "registered_at": "...", "revoked": false }
```

The `revoked` field is forward-compat — today a revoked token is rejected before this handler runs (401). Either path drives the same client-side behavior: tray turns red, uploads stop, the user needs to re-register.

## Revocation — what the user sees

1. Admin revokes the agent from the web UI (sets `revoked_at`).
2. Next heartbeat from the agent → 401.
3. Agent:
   - Logs `heartbeat_unauthorized`.
   - Sets tray icon to **red** (`R.ico`).
   - Stops the watcher — in-flight uploads are not cancelled, but no new files are shipped.
4. User right-clicks tray → **Re-register...** to clear the token and trigger a fresh first-run flow on the next launch.

## Client version

`CLIENT_VERSION` in `first_run.py` is sent on both `/register` and every heartbeat. The server stores it so administrators can see which build a given machine is running and flag obsolete clients.
