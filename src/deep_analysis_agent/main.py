"""Agent entry point — wires config, logging, instance lock, watcher, tray."""

from __future__ import annotations

import sys
from pathlib import Path

import structlog

from .config import load_config
from .dedup import DedupStore
from .instance_lock import AlreadyRunningError, InstanceLock
from .logging import configure_logging
from .paths import dedup_path
from .tray import TrayIcon
from .watcher import LogWatcher


def main() -> None:
    config = load_config()
    configure_logging(config)
    log = structlog.get_logger("deep_analysis_agent.main")

    try:
        lock = InstanceLock()
        lock.__enter__()
    except AlreadyRunningError:
        log.error("another agent instance is already running — exiting")
        sys.exit(1)

    try:
        dedup = DedupStore(dedup_path())
        tray = TrayIcon(config=config)

        def on_file_ready(path: Path) -> None:
            try:
                sha = dedup.hash_file(path)
            except OSError:
                log.exception("hash_failed", path=str(path))
                return
            if dedup.is_seen(sha):
                log.debug("skip_seen", path=str(path), sha256=sha[:8])
                return
            tray.set_state("uploading")
            # TODO(W8b): auth + HTTP shipping here.
            log.info("file_ready", path=str(path), sha256=sha[:8])
            dedup.mark_seen(sha, path)
            tray.set_state("idle")

        watcher = LogWatcher(
            watch_dir=config.mtgo.log_dir,
            suffixes=frozenset(s.lower() for s in config.mtgo.watched_suffixes),
            stability_seconds=config.mtgo.stability_seconds,
            on_file_ready=on_file_ready,
        )
        watcher.start()

        def _on_quit() -> None:
            watcher.stop()
            dedup.close()

        tray.start(on_quit=_on_quit)
    finally:
        lock.__exit__(None, None, None)


if __name__ == "__main__":  # pragma: no cover
    main()
