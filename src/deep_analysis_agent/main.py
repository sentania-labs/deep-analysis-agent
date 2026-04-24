"""Agent entry point — wires config, logging, instance lock, watcher, tray."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import threading
from pathlib import Path

import structlog

from . import auth, shipper
from .config import AppConfig, load_config, save_config
from .dedup import DedupStore
from .first_run import CLIENT_VERSION, run_first_run_flow
from .instance_lock import AlreadyRunningError, InstanceLock
from .logging import configure_logging
from .paths import dedup_path
from .tray import TrayIcon
from .watcher import LogWatcher


async def _heartbeat_loop(
    config: AppConfig,
    tray: TrayIcon,
    stop_event: asyncio.Event,
    revoked_event: asyncio.Event,
    log: structlog.stdlib.BoundLogger,
) -> None:
    interval = max(30, config.agent.heartbeat_interval_seconds)
    assert config.agent.api_token is not None
    while not stop_event.is_set():
        try:
            result = await auth.heartbeat(
                config.server.url,
                config.agent.api_token,
                CLIENT_VERSION,
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
    try:
        sha = dedup.hash_file(path)
    except OSError:
        log.exception("hash_failed", path=str(path))
        return
    if dedup.is_seen(sha):
        log.debug("skip_seen", path=str(path), sha256=sha[:8])
        return

    assert config.agent.api_token is not None
    tray.set_state("uploading")
    try:
        result = await shipper.ship_file(
            config.server.url,
            config.agent.api_token,
            path,
            sha,
            tls_verify=config.server.tls_verify,
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


def _handle_squirrel_hooks() -> bool:
    """Return True if a Squirrel hook was handled (caller should exit 0)."""
    if len(sys.argv) < 2:
        return False
    arg = sys.argv[1].lower()
    # For v0.4.0 all hooks are no-ops — Squirrel's built-in helper handles
    # shortcut creation/removal. Future versions can add post-update migrations,
    # re-registration prompts, etc. here.
    return arg in _SQUIRREL_HOOKS


async def _async_main() -> int:
    config = load_config()
    configure_logging(config)
    log = structlog.get_logger("deep_analysis_agent.main")

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

        tray = TrayIcon(config=config, on_reregister=_on_reregister)

        def on_file_ready(path: Path) -> None:
            fut = asyncio.run_coroutine_threadsafe(
                _handle_file(path, config, dedup, tray, revoked_event, log), loop
            )
            try:
                fut.result(timeout=600)
            except Exception:
                log.exception("handle_file_raised", path=str(path))

        watcher = LogWatcher(
            watch_dir=config.mtgo.log_dir,
            suffixes=frozenset(s.lower() for s in config.mtgo.watched_suffixes),
            stability_seconds=config.mtgo.stability_seconds,
            on_file_ready=on_file_ready,
        )
        watcher.start()

        hb_task = asyncio.create_task(
            _heartbeat_loop(config, tray, stop_event, revoked_event, log),
            name="heartbeat",
        )

        async def _watch_revoked() -> None:
            await revoked_event.wait()
            log.warning("stopping watcher due to revocation")
            watcher.stop()

        rev_task = asyncio.create_task(_watch_revoked(), name="revoke-watch")

        quit_event = threading.Event()

        def _on_quit() -> None:
            quit_event.set()
            watcher.stop()
            dedup.close()

        # Run tray in a thread so its blocking .run() doesn't hog the loop.
        tray_thread = threading.Thread(
            target=tray.start, args=(_on_quit,), name="tray", daemon=True
        )
        tray_thread.start()

        # Wait for quit signal.
        while not quit_event.is_set():
            await asyncio.sleep(0.2)

        stop_event.set()
        hb_task.cancel()
        rev_task.cancel()
        for t in (hb_task, rev_task):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        return 0
    finally:
        lock.__exit__(None, None, None)


def main() -> None:
    if _handle_squirrel_hooks():
        sys.exit(0)
    sys.exit(asyncio.run(_async_main()))


if __name__ == "__main__":  # pragma: no cover
    main()
