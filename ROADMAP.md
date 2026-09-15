# Deep Analysis Agent — Roadmap

Plain-language status of what the agent does today and what's next. Written for an operator, not a developer.

Shipped versions are recorded in [CHANGELOG.md](CHANGELOG.md), though that file has fallen behind the last several releases (currently stops at v0.4.10; the repository is actually at v0.7.0). Treat the commit history and this roadmap as the current truth until CHANGELOG.md is brought forward, which is not part of this update.

---

## Built and working

Everything below has shipped and is live in the current release (v0.7.0):

- **Update check that actually checks, and now tells the truth about the result.** The tray's "Check for Updates" runs a real check in the background and reports success only once the installed update is verified, not just when the installer process started. See [Updates](README.md#installation).
- **Pause Sync.** Tray toggle to stop watching/uploading without quitting the agent. Picks back up on resume.
- **Bulk startup sync.** Startup no longer re-checks every log file one at a time against the dedup database; it does one bulk comparison and only queues files that are new or changed.
- **600-second stability gate with match-completion detection.** The agent waits for a log file to go quiet for 10 minutes (matching MTGO's own match timeout) before treating it as finished, then scans for a clear winner/loser. If it can't tell, it ships the file anyway and flags it, so the server can hold it for review instead of silently guessing.
- **Autostart on Windows login**, with a tray toggle to opt out. Survives updates: an earlier bug that could re-launch a stale version after an update (issue #42) is fixed.
- **First-run registration failures are visible.** Earlier, a failed registration could fail silently with no window open and nothing on screen. Failures now show a message box with retry, for both the registration-code and email/password paths.
- **Full settings coverage in the GUI.** Every operator-editable setting now has a control in the Settings window, including the advanced MTGO file-filter globs and CardDataSource (card catalog) enable/directory controls that previously required hand-editing `config.toml`. This satisfies the "every setting has a GUI option" rule for the settings that exist today.
- **Squirrel packaging is fully wired**, not just scaffolding. Pushing a `vX.Y.Z` tag builds the installer, packages it with Squirrel, and publishes it to a GitHub Release automatically. The one open gap is that the auto-removal of the Windows autostart entry on uninstall is best-effort and only takes effect once a build goes through the Squirrel-aware packaging path.

---

## Next up, in priority order

### 1. Card data source changes should apply without a restart (issue #64)

Turning the card catalog on/off, or changing its folder, saves correctly today but only takes effect after the agent restarts, and the Settings window has to tell the operator that. Follow-on from the settings work above. Small fix: make the running agent pick up the change on the next config reload instead of only at startup.

**Why it's next:** it's the direct loose end from the settings-completeness work just shipped, and it's a small, well-scoped fix.

### 2. Exact upload reconciliation (issue #41)

Today the agent trusts its own local record of what it already uploaded. If that local record and the server ever disagree by a small amount, nothing catches it automatically. Two coarser safety nets already exist: the agent resyncs itself if its count and the server's count drift far apart, and an administrator can force a full re-send. Building an exact, file-by-file reconciliation on top of that would close the last narrow gap, but it requires new work on the server side too, not just the agent.

**Why it's here and not higher:** it is a real feature request, but it is large (spans both this repo and the server repo) and the existing coarse safety nets already catch the scenarios that matter most. This needs a decision from the captain on whether that's good enough before more work goes into it. See the deferred item below.

### 3. Review-gate hook performance (issue #54)

A development-tooling hook that checks git commands before they run gets noticeably slower on long chains of git commands (measured multi-second delay around 500 chained commands). It still gives the correct answer every time, it's just slow. This affects contributors working in this repo, not the shipped agent.

**Why it's last:** it's a real but low-stakes annoyance in the development workflow, not something an end user of the agent ever sees.

---

## Deferred, and why

- **Exact upload reconciliation, full scope (issue #41).** Deferred pending a captain decision on whether the current coarse recovery (resync on count drift, admin-triggered full reingest) is good enough, versus building the larger cross-repository exact-reconciliation feature. Not rejected, just waiting on that call.
- **Server-side "inconclusive match" holding pen.** The agent already flags matches it can't confidently score as inconclusive and ships them anyway. What the server does with that flag (an admin review queue) lives in the `deep-analysis-server` repository, not here, and isn't tracked as agent work.

---

## Rejected

_Nothing has been proposed and turned down. This section stays empty until that happens._
