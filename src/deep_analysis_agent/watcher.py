"""Watchdog-based MTGO log directory watcher with a stability gate.

A file is only yielded once its size + mtime stop changing for
`stability_seconds`. Stability is checked BEFORE any downstream
hashing (the v0.3.7 ordering rule).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

FileReadyCallback = Callable[[Path], None]

_POLL_INTERVAL = 0.2  # seconds between stability polls
_MAX_STABILITY_WAIT = 120.0  # give up after this much continuous churn


class _Handler(FileSystemEventHandler):
    def __init__(self, enqueue: Callable[[Path], None], suffixes: frozenset[str]) -> None:
        self._enqueue = enqueue
        self._suffixes = suffixes

    def _maybe(self, path_str: str) -> None:
        path = Path(path_str)
        if path.suffix.lower() in self._suffixes:
            self._enqueue(path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._maybe(str(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._maybe(str(event.src_path))


class LogWatcher:
    def __init__(
        self,
        watch_dir: Path,
        suffixes: frozenset[str],
        stability_seconds: float,
        on_file_ready: FileReadyCallback,
    ) -> None:
        self._dir = watch_dir
        self._suffixes = frozenset(s.lower() for s in suffixes)
        self._stability = stability_seconds
        self._cb = on_file_ready
        self._queue: queue.Queue[Path | None] = queue.Queue()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._observer: Any | None = None

    @property
    def started(self) -> bool:
        return self._worker is not None

    def start(self) -> None:
        if self._worker is not None:
            return
        if not self._dir.is_dir():
            logger.warning("watch_dir_missing path=%s", self._dir)
            # Leave self._worker None so stop() is idempotent; caller surfaces error state.
            return
        self._worker = threading.Thread(target=self._run, name="deep-analysis-watcher", daemon=True)
        self._worker.start()
        self._observer = Observer()
        self._observer.schedule(
            _Handler(self._enqueue, self._suffixes), str(self._dir), recursive=True
        )
        self._observer.start()
        self._startup_scan()
        logger.info("watcher started on %s", self._dir)

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except Exception:
                logger.exception("observer stop raised")
            self._observer = None
        if self._worker is not None:
            self._queue.put(None)
            self._worker.join(timeout=10)
            self._worker = None

    def _enqueue(self, path: Path) -> None:
        self._queue.put(path)

    def _startup_scan(self) -> None:
        if not self._dir.exists():
            return
        count = 0
        for p in self._dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in self._suffixes:
                self._queue.put(p)
                count += 1
        logger.info("watcher startup scan queued %d file(s)", count)

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            try:
                if self._wait_stable(item):
                    self._cb(item)
            except Exception:
                logger.exception("watcher callback failed for %s", item)

    def _wait_stable(self, path: Path) -> bool:
        if not path.is_file():
            return False
        deadline = time.monotonic() + _MAX_STABILITY_WAIT
        try:
            prev = path.stat()
        except OSError:
            return False
        last_change = time.monotonic()
        while not self._stop.is_set():
            time.sleep(_POLL_INTERVAL)
            try:
                cur = path.stat()
            except OSError:
                return False
            if cur.st_mtime == prev.st_mtime and cur.st_size == prev.st_size:
                if time.monotonic() - last_change >= self._stability:
                    return True
            else:
                last_change = time.monotonic()
                prev = cur
            if time.monotonic() > deadline:
                logger.info("watcher gave up on stability for %s", path)
                return False
        return False
