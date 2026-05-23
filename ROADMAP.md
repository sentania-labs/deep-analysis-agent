# Deep Analysis Agent — Roadmap

Active and planned outcomes for the Deep Analysis agent. Each outcome is named and scoped so it can be picked up and shipped on its own.

Shipped versions are recorded in [CHANGELOG.md](CHANGELOG.md).

---

## Active

_All items shipped in v0.4.10._

### 1. Manual update check actually checks

The "Check for Updates" tray menu item currently shows a dismissive notification ("Squirrel checks for updates on startup and daily — no manual check needed"). It should invoke Squirrel's update check and report the result: "Up to date (v0.4.7)" or "Update available — installing on next restart."

- **Acceptance criteria:**
  - Clicking "Check for Updates" triggers a real Squirrel update check
  - Tray notification reports the outcome (up to date / update found / check failed)
  - Non-blocking — runs in background, doesn't freeze the tray
- **Status:** Done (v0.4.10)

### 2. Pause sync

Tray menu toggle to pause file watching and upload without quitting the agent. Useful when the user wants the agent running but doesn't want uploads happening (bandwidth, privacy, testing).

- **Acceptance criteria:**
  - New tray menu item: "Pause Sync" / "Resume Sync" (toggles)
  - When paused: watcher stops, no new files are queued or uploaded
  - Tray icon/status reflects paused state
  - State survives config reload but not app restart (starts unpaused)
  - Files created while paused are picked up on resume (startup scan runs on resume)
- **Status:** Done (v0.4.10)

### 3. Bulk startup sync (upload optimization)

Replace the current startup scan (queue every matching file → per-file dedup check → hash → upload) with a bulk directory-vs-DB diff. At startup, generate a directory listing of matching files with size/mtime, compare against the SQLite dedup DB in one pass, and only queue files that are new or changed. Optionally verify against the server's known uploads to catch local DB drift.

Current pain: every startup re-enqueues all matching files, and each one individually hits `is_path_unchanged()`. With many files this is redundant work — the answer is almost always "skip."

- **Acceptance criteria:**
  - Startup scan does a single bulk comparison (dir listing vs DB) instead of per-file enqueue-then-check
  - Only new or changed files (by size/mtime) enter the upload pipeline
  - Optional server-side verification: compare local DB hashes against server's known uploads, flag/re-upload any gaps
  - Watchdog still handles files created after startup (real-time)
  - No regression: files must never be silently lost
- **Status:** Done (v0.4.10)

### 4. Stability gate + finalized-match detection

The agent currently ships intermediate snapshots of in-progress matches because the file-stability gate is too short — a match log that's mid-game can look "stable" between turns and get uploaded as if complete. Raise the stability gate to align with MTGO's match timeout, and once the file goes stable, scan the tail for a clear winner/loser signal to decide whether the match is finalized or inconclusive.

- **Acceptance criteria:**
  - `stability_seconds` default raised to 600s (aligns with MTGO match timeout)
  - When a file becomes stable for 600s, agent scans the file tail for a clear winner/loser signal before shipping
  - Clear winner/loser found → ship as a complete match (current happy path)
  - No clear winner/loser → ship anyway, flagged as inconclusive, so the server can route it to an admin-review holding pen (server-side holding pen is a separate outcome, not implemented here)
  - `stability_seconds` remains configurable (someone may want a shorter gate for testing)
- **Status:** Done (unreleased — bundled with autostart in v0.5.x)
- **Dependencies:** None on the agent side. Server-side holding-pen feature (`sentania-labs/deep-analysis-server` issue #71) is a parallel/follow-up outcome, not blocking.

### 5. Autostart on Windows login

The agent should launch automatically when the user logs in to Windows, so file watching and uploads happen without the user having to remember to start the tray app.

- **Acceptance criteria:**
  - Agent launches automatically when user logs in to Windows (no manual start needed)
  - User can opt out (tray menu toggle or installer option — whichever is simpler)
  - Plays nicely with the existing PyInstaller + Squirrel install/update flow
- **Status:** Done (unreleased — bundled with stability gate in v0.5.x)
- **Dependencies:** None

---

## Cleanup

- **Squirrel packaging** — installer scaffolding exists but Squirrel integration isn't wired end-to-end yet. Needed before #1 can work outside dev builds.

---

## Future Ideas (Unprioritized)

_Empty._
