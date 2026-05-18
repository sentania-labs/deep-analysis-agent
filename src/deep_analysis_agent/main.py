"""Agent entry point — wires config, logging, instance lock, watcher, tray."""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import structlog

from . import __version__, auth, card_data_source, shipper
from .config import AppConfig, load_config, save_config
from .dedup import DedupStore
from .first_run import run_first_run_flow
from .instance_lock import AlreadyRunningError, InstanceLock
from .logging import configure_logging, log_file_path
from .paths import app_data_dir, config_path, dedup_path
from .tray import TrayIcon
from .watcher import LogWatcher

_STARTUP_BANNER_RULE = "=" * 60

_HASH_RETRIES = 3
_HASH_RETRY_DELAY = 2.0

# Mapping of filename glob patterns to server content_type values.
_CONTENT_TYPE_MAP: list[tuple[str, str]] = [
    ("grouping *.xml", "decklist"),
    ("Match_GameLog_*.dat", "match-log"),
]


def detect_content_type(filename: str) -> str:
    """Return the server content_type for a file based on its name."""
    for pattern, ct in _CONTENT_TYPE_MAP:
        if fnmatch.fnmatch(filename, pattern):
            return ct
    return "unknown"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a dotted version string into a tuple of ints for comparison."""
    parts: list[int] = []
    for segment in v.strip().split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            break
    return tuple(parts)


def _log_startup_banner(config: AppConfig, log: structlog.stdlib.BoundLogger) -> None:
    log.info(_STARTUP_BANNER_RULE)
    log.info("Deep Analysis agent starting", version=__version__)
    log.info(_STARTUP_BANNER_RULE)
    log.info(
        "agent_start",
        version=__version__,
        agent_id=config.agent.agent_id,
        config_path=str(config_path()),
        log_path=str(log_file_path(config)),
        server_url=config.server.url,
        log_dir=str(config.mtgo.log_dir),
    )


async def _heartbeat_loop(
    config: AppConfig,
    tray: TrayIcon,
    dedup: DedupStore,
    watcher_box: list[LogWatcher | None],
    build_watcher: Callable[[], LogWatcher],
    stop_event: asyncio.Event,
    revoked_event: asyncio.Event,
    log: structlog.stdlib.BoundLogger,
) -> None:
    assert config.agent.api_token is not None
    resync_done = False
    version_warned = False
    while not stop_event.is_set():
        # Re-read each iteration so SettingsWindow reload picks up new interval.
        interval = max(30, config.agent.heartbeat_interval_seconds)
        local_count = dedup.count()
        try:
            result = await auth.heartbeat(
                config.server.url,
                config.agent.api_token,
                __version__,
                local_file_count=local_count,
                tls_verify=config.server.tls_verify,
            )
        except auth.HeartbeatError as exc:
            log.warning("heartbeat_failed", error=str(exc))
            if "unauthorized" in str(exc).lower():
                log.error("heartbeat_unauthorized — agent token revoked or invalid")
                tray.set_state("error")
                revoked_event.set()
                return
        else:
            if result.revoked:
                log.error("heartbeat_reports_revoked — stopping uploads")
                tray.set_state("error")
                revoked_event.set()
                return
            log.debug("heartbeat_ok", status=result.status)

            # Version floor check — warn once per session.
            if not version_warned and result.min_agent_version:
                agent_ver = _parse_version(__version__)
                required_ver = _parse_version(result.min_agent_version)
                if agent_ver < required_ver:
                    version_warned = True
                    log.warning(
                        "version_below_minimum",
                        agent=__version__,
                        required=result.min_agent_version,
                    )
                    tray.set_state("error")
                    if tray._icon is not None:
                        try:
                            tray._icon.notify(
                                f"Update required: server requires agent "
                                f"v{result.min_agent_version} or newer",
                                "Deep Analysis",
                            )
                        except Exception:
                            log.debug("tray_notify_failed")

            # Resync check: trigger once per session if server count is
            # significantly lower than local dedup count.
            if (
                not resync_done
                and local_count > 0
                and (
                    result.upload_count < local_count * 0.8
                    or local_count - result.upload_count > 50
                )
            ):
                log.warning(
                    "resync_triggered",
                    server_count=result.upload_count,
                    local_count=local_count,
                )
                resync_done = True
                dedup.clear()
                # Restart the watcher to trigger a fresh startup scan,
                # but respect the user's pause state.
                if not tray._paused:
                    old = watcher_box[0]
                    if old is not None:
                        old.stop()
                    new_watcher = build_watcher()
                    new_watcher.start()
                    watcher_box[0] = new_watcher
                    tray.set_state("uploading")
                else:
                    log.info("resync_deferred_paused")

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval)


async def _handle_file(
    path: Path,
    config: AppConfig,
    dedup: DedupStore,
    tray: TrayIcon,
    revoked_event: asyncio.Event,
    log: structlog.stdlib.BoundLogger,
) -> None:
    if revoked_event.is_set():
        log.info("skip_revoked", path=str(path))
        return
    if dedup.is_path_unchanged(path):
        log.info("skip_already_uploaded", path=str(path))
        return
    sha: str | None = None
    for attempt in range(1, _HASH_RETRIES + 1):
        try:
            sha = await asyncio.to_thread(dedup.hash_file, path)
            break
        except PermissionError:
            if attempt < _HASH_RETRIES:
                log.warning(
                    "hash_retry",
                    path=str(path),
                    attempt=attempt,
                    delay=_HASH_RETRY_DELAY,
                )
                await asyncio.sleep(_HASH_RETRY_DELAY)
            else:
                log.error("hash_failed_after_retries", path=str(path), attempts=_HASH_RETRIES)
                return
        except OSError:
            log.exception("hash_failed", path=str(path))
            return
    assert sha is not None
    if dedup.is_seen(sha):
        log.info("skip_seen", path=str(path), sha256=sha[:8])
        return

    assert config.agent.api_token is not None
    ct = detect_content_type(path.name)
    tray.set_state("uploading")
    try:
        result = await shipper.ship_file(
            config.server.url,
            config.agent.api_token,
            path,
            sha,
            tls_verify=config.server.tls_verify,
            content_type=ct,
            original_filename=path.name,
        )
    except shipper.ShipError:
        log.exception("ship_failed", path=str(path), sha256=sha[:8])
        tray.set_state("error")
        return

    dedup.mark_seen(sha, path)
    tray.set_state("idle")
    log.info(
        "file_shipped",
        path=str(path),
        sha256=sha[:8],
        deduped=result.deduped,
        file_id=result.file_id,
    )


_SQUIRREL_HOOKS = {
    "--squirrel-install",
    "--squirrel-updated",
    "--squirrel-obsolete",
    "--squirrel-uninstall",
}


_MARKER_JUST_UPDATED = "just_updated"
_MARKER_FIRST_RUN = "first_run_pending"


def _write_marker(name: str) -> None:
    """Write a zero-byte marker file to %LOCALAPPDATA%\\DeepAnalysis\\<name>.

    The main app checks for these on startup and acts on them (e.g. show
    a toast notification), then deletes the marker.  Best-effort — if the
    write fails we just log and move on.
    """
    try:
        marker_dir = app_data_dir()
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / name).write_text(__version__, encoding="utf-8")
    except Exception:
        # Marker write is nice-to-have; never block the hook.
        pass


def _handle_squirrel_hooks() -> bool:
    """Return True if a Squirrel hook was handled (caller should exit 0)."""
    if len(sys.argv) < 2:
        return False
    arg = sys.argv[1].lower()
    if arg not in _SQUIRREL_HOOKS:
        return False

    if arg == "--squirrel-updated":
        _write_marker(_MARKER_JUST_UPDATED)
    elif arg == "--squirrel-install":
        _write_marker(_MARKER_FIRST_RUN)

    return True


_LAST_VERSION_FILE = ".last_version"


def _check_version_upgrade(log: structlog.stdlib.BoundLogger) -> str | None:
    """Compare current version against the persisted last-run version.

    Returns the *previous* version string when an upgrade is detected (so the
    caller can show a notification), or None if the version is unchanged or
    this is the first run.  Writes the current version back to disk either way.
    """
    version_file = app_data_dir() / _LAST_VERSION_FILE
    previous: str | None = None
    try:
        if version_file.exists():
            previous = version_file.read_text(encoding="utf-8").strip()
    except Exception:
        log.debug("last_version_read_failed")

    upgraded_from: str | None = None
    if previous and previous != __version__:
        upgraded_from = previous
        log.info("version_upgrade_detected", previous=previous, current=__version__)

    try:
        version_file.parent.mkdir(parents=True, exist_ok=True)
        version_file.write_text(__version__, encoding="utf-8")
    except Exception:
        log.debug("last_version_write_failed")

    return upgraded_from


def _consume_marker(name: str) -> str | None:
    """Read and delete a Squirrel marker file.  Returns its contents or None."""
    marker = app_data_dir() / name
    try:
        if marker.exists():
            content = marker.read_text(encoding="utf-8").strip()
            marker.unlink(missing_ok=True)
            return content or "unknown"
    except Exception:
        pass
    return None


def _schedule_tray_notification(
    tray: TrayIcon,
    message: str,
    title: str = "Deep Analysis",
    delay: float = 1.5,
) -> None:
    """Fire a tray toast after a short delay (gives pystray time to initialise)."""

    def _notify() -> None:
        import time

        time.sleep(delay)
        if tray._icon is not None:
            with contextlib.suppress(Exception):
                tray._icon.notify(message, title)

    threading.Thread(target=_notify, name="startup-notify", daemon=True).start()


async def _async_main() -> int:
    config = load_config()
    configure_logging(config)
    log = structlog.get_logger("deep_analysis_agent.main")
    _log_startup_banner(config, log)

    if not config.agent.api_token:
        log.info("first_run_flow_start")
        ok = await run_first_run_flow(config)
        if not ok:
            log.error("first_run_flow_aborted — exiting")
            return 1
        # Reload with the saved token.
        config = load_config()

    try:
        lock = InstanceLock()
        lock.__enter__()
    except AlreadyRunningError:
        log.error("another agent instance is already running — exiting")
        return 1

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    revoked_event = asyncio.Event()

    try:
        dedup = DedupStore(dedup_path())

        def _on_reregister() -> None:
            config.agent.agent_id = None
            config.agent.api_token = None
            save_config(config)
            log.warning("reregister_requested — restart agent to complete")

        def on_file_ready(path: Path) -> None:
            fut = asyncio.run_coroutine_threadsafe(
                _handle_file(path, config, dedup, tray, revoked_event, log), loop
            )
            try:
                fut.result(timeout=600)
            except Exception:
                log.exception("handle_file_raised", path=str(path))

        # Mutable container so on_reload can swap the active watcher in place.
        watcher_box: list[LogWatcher | None] = [None]

        def _build_watcher() -> LogWatcher:
            return LogWatcher(
                watch_dir=config.mtgo.log_dir,
                suffixes=frozenset(s.lower() for s in config.mtgo.watched_suffixes),
                stability_seconds=config.mtgo.stability_seconds,
                on_file_ready=on_file_ready,
                name_globs=config.mtgo.watched_name_globs,
                dedup=dedup,
            )

        def _on_reload(_new_config: AppConfig) -> None:
            old = watcher_box[0]
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    log.exception("watcher_stop_failed_during_reload")
            new_watcher = _build_watcher()
            new_watcher.start()
            watcher_box[0] = new_watcher
            if not new_watcher.started:
                log.error(
                    "watcher_not_started_after_reload — MTGO log directory missing",
                    log_dir=str(config.mtgo.log_dir),
                )
                tray.set_state("watcher_disabled")
            else:
                tray.set_state("idle")

        def _on_pause(paused: bool) -> None:
            if paused:
                current = watcher_box[0]
                if current is not None:
                    current.stop()
                    log.info("watcher_stopped_by_pause")
            else:
                new_watcher = _build_watcher()
                new_watcher.start()
                watcher_box[0] = new_watcher
                if not new_watcher.started:
                    log.error(
                        "watcher_not_started_after_resume — MTGO log directory missing",
                        log_dir=str(config.mtgo.log_dir),
                    )
                    tray.set_state("watcher_disabled")
                else:
                    log.info("watcher_resumed")

        tray = TrayIcon(
            config=config,
            version=__version__,
            on_reregister=_on_reregister,
            on_reload=_on_reload,
            on_pause=_on_pause,
        )

        watcher = _build_watcher()
        watcher.start()
        watcher_box[0] = watcher
        if not watcher.started:
            log.error(
                "watcher_not_started — MTGO log directory missing; "
                "fix mtgo.log_dir in Settings and restart",
                log_dir=str(config.mtgo.log_dir),
            )
            tray.set_state("watcher_disabled")

        # Ship CardDataSource reference data if changed (non-blocking).
        cds_task = asyncio.create_task(
            card_data_source.check_and_ship(config, dedup),
            name="card-data-source",
        )

        hb_task = asyncio.create_task(
            _heartbeat_loop(
                config,
                tray,
                dedup,
                watcher_box,
                _build_watcher,
                stop_event,
                revoked_event,
                log,
            ),
            name="heartbeat",
        )

        async def _watch_revoked() -> None:
            await revoked_event.wait()
            log.warning("stopping watcher due to revocation")
            current = watcher_box[0]
            if current is not None:
                current.stop()

        rev_task = asyncio.create_task(_watch_revoked(), name="revoke-watch")

        quit_event = threading.Event()

        def _on_quit() -> None:
            quit_event.set()
            current = watcher_box[0]
            if current is not None:
                current.stop()
            dedup.close()

        # Run tray in a thread so its blocking .run() doesn't hog the loop.
        tray_thread = threading.Thread(
            target=tray.start, args=(_on_quit,), name="tray", daemon=True
        )
        tray_thread.start()

        # --- Startup notifications (Squirrel markers + version-change) ---
        squirrel_updated = _consume_marker(_MARKER_JUST_UPDATED)
        squirrel_first_run = _consume_marker(_MARKER_FIRST_RUN)
        upgraded_from = _check_version_upgrade(log)

        if squirrel_updated:
            _schedule_tray_notification(tray, f"Deep Analysis updated to v{__version__}")
        elif squirrel_first_run:
            _schedule_tray_notification(tray, f"Welcome to Deep Analysis v{__version__}!")
        elif upgraded_from:
            _schedule_tray_notification(tray, f"Updated to v{__version__}")

        # Wait for quit signal.
        while not quit_event.is_set():
            await asyncio.sleep(0.2)

        stop_event.set()
        cds_task.cancel()
        hb_task.cancel()
        rev_task.cancel()
        for t in (cds_task, hb_task, rev_task):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        return 0
    finally:
        lock.__exit__(None, None, None)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--version":
        print(f"DeepAnalysisAgent {__version__}")
        sys.exit(0)
    if _handle_squirrel_hooks():
        sys.exit(0)
    sys.exit(asyncio.run(_async_main()))


if __name__ == "__main__":  # pragma: no cover
    main()
