"""Tests for LogWatcher stability-check debouncing and name-glob filter."""

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
        name_globs=["Match_GameLog_*.dat"],
    )
    watcher.start()
    try:
        target = tmp_path / "Match_GameLog_12345.dat"
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
        name_globs=["Match_GameLog_*.dat"],
    )
    watcher.start()
    try:
        (tmp_path / "Match_GameLog_other.txt").write_bytes(b"ignore me")
        time.sleep(0.6)
        assert seen == []
    finally:
        watcher.stop()


def test_non_matching_name_ignored(tmp_path: Path) -> None:
    seen: list[Path] = []

    watcher = LogWatcher(
        watch_dir=tmp_path,
        suffixes=frozenset({".dat"}),
        stability_seconds=0.2,
        on_file_ready=seen.append,
        name_globs=["Match_GameLog_*.dat"],
    )
    watcher.start()
    try:
        (tmp_path / "GChat.dat").write_bytes(b"chat noise")
        (tmp_path / "IdentityV2.dat").write_bytes(b"identity blob")
        time.sleep(0.6)
        assert seen == []
    finally:
        watcher.stop()


def test_matching_name_fires(tmp_path: Path) -> None:
    seen: list[Path] = []
    event = threading.Event()

    def on_ready(p: Path) -> None:
        seen.append(p)
        event.set()

    watcher = LogWatcher(
        watch_dir=tmp_path,
        suffixes=frozenset({".dat"}),
        stability_seconds=0.2,
        on_file_ready=on_ready,
        name_globs=["Match_GameLog_*.dat"],
    )
    watcher.start()
    try:
        target = tmp_path / "Match_GameLog_20240501_123456.dat"
        target.write_bytes(b"real game log")
        assert event.wait(timeout=3.0), "FileReadyCallback never fired for Match_GameLog file"
        assert target in seen
    finally:
        watcher.stop()


def test_multiple_globs_match_xml(tmp_path: Path) -> None:
    """Watcher configured with multiple globs picks up grouping XML files."""
    seen: list[Path] = []
    event = threading.Event()

    def on_ready(p: Path) -> None:
        seen.append(p)
        event.set()

    watcher = LogWatcher(
        watch_dir=tmp_path,
        suffixes=frozenset({".dat", ".xml"}),
        stability_seconds=0.2,
        on_file_ready=on_ready,
        name_globs=["Match_GameLog_*.dat", "grouping *.xml"],
    )
    watcher.start()
    try:
        target = tmp_path / "grouping 12345.xml"
        target.write_bytes(b"<grouping>deck data</grouping>")
        assert event.wait(timeout=3.0), "FileReadyCallback never fired for grouping XML"
        assert target in seen
    finally:
        watcher.stop()


def test_multiple_globs_match_dat(tmp_path: Path) -> None:
    """Multiple globs still match the original .dat pattern."""
    seen: list[Path] = []
    event = threading.Event()

    def on_ready(p: Path) -> None:
        seen.append(p)
        event.set()

    watcher = LogWatcher(
        watch_dir=tmp_path,
        suffixes=frozenset({".dat", ".xml"}),
        stability_seconds=0.2,
        on_file_ready=on_ready,
        name_globs=["Match_GameLog_*.dat", "grouping *.xml"],
    )
    watcher.start()
    try:
        target = tmp_path / "Match_GameLog_99999.dat"
        target.write_bytes(b"game log data")
        assert event.wait(timeout=3.0), "FileReadyCallback never fired for .dat with multi-glob"
        assert target in seen
    finally:
        watcher.stop()


def test_multiple_globs_reject_non_matching(tmp_path: Path) -> None:
    """Files not matching ANY glob in the list are ignored."""
    seen: list[Path] = []

    watcher = LogWatcher(
        watch_dir=tmp_path,
        suffixes=frozenset({".dat", ".xml"}),
        stability_seconds=0.2,
        on_file_ready=seen.append,
        name_globs=["Match_GameLog_*.dat", "grouping *.xml"],
    )
    watcher.start()
    try:
        (tmp_path / "GChat.dat").write_bytes(b"chat noise")
        (tmp_path / "settings.xml").write_bytes(b"<settings/>")
        time.sleep(0.6)
        assert seen == []
    finally:
        watcher.stop()


def test_no_globs_matches_any_name(tmp_path: Path) -> None:
    """When name_globs is None (or empty), any file matching suffixes is accepted."""
    seen: list[Path] = []
    event = threading.Event()

    def on_ready(p: Path) -> None:
        seen.append(p)
        event.set()

    watcher = LogWatcher(
        watch_dir=tmp_path,
        suffixes=frozenset({".dat"}),
        stability_seconds=0.2,
        on_file_ready=on_ready,
        name_globs=None,
    )
    watcher.start()
    try:
        target = tmp_path / "anything.dat"
        target.write_bytes(b"data")
        assert event.wait(timeout=3.0), "FileReadyCallback never fired with no glob filter"
        assert target in seen
    finally:
        watcher.stop()
