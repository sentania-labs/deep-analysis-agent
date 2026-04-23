"""Tests for LogWatcher stability-check debouncing."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from deep_analysis_agent.watcher import LogWatcher


def test_stability_fires_after_file_stops_changing(tmp_path: Path) -> None:
    seen: list[Path] = []
    event = threading.Event()

    def on_ready(p: Path) -> None:
        seen.append(p)
        event.set()

    watcher = LogWatcher(
        watch_dir=tmp_path,
        suffixes=frozenset({".dat"}),
        stability_seconds=0.3,
        on_file_ready=on_ready,
    )
    watcher.start()
    try:
        target = tmp_path / "m.dat"
        target.write_bytes(b"a")
        # Churn for ~0.6s: size keeps changing, should NOT fire.
        for i in range(6):
            time.sleep(0.1)
            target.write_bytes(b"a" * (i + 2))
        # Stop writing. Should fire within stability_seconds + slack.
        assert event.wait(timeout=3.0), "FileReadyCallback never fired"
        assert target in seen
    finally:
        watcher.stop()


def test_non_matching_suffix_ignored(tmp_path: Path) -> None:
    seen: list[Path] = []

    watcher = LogWatcher(
        watch_dir=tmp_path,
        suffixes=frozenset({".dat"}),
        stability_seconds=0.2,
        on_file_ready=seen.append,
    )
    watcher.start()
    try:
        (tmp_path / "other.txt").write_bytes(b"ignore me")
        time.sleep(0.6)
        assert seen == []
    finally:
        watcher.stop()
