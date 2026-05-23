"""Tests for LogWatcher stability-check debouncing and name-glob filter."""

from __future__ import annotations

import os
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


def test_watcher_respects_long_stability_gate(tmp_path: Path) -> None:
    """The watcher must not fire before `stability_seconds` elapses with no churn."""
    seen: list[Path] = []
    event = threading.Event()

    def on_ready(p: Path) -> None:
        seen.append(p)
        event.set()

    watcher = LogWatcher(
        watch_dir=tmp_path,
        suffixes=frozenset({".dat"}),
        stability_seconds=1.0,
        on_file_ready=on_ready,
        name_globs=["Match_GameLog_*.dat"],
    )
    watcher.start()
    try:
        target = tmp_path / "Match_GameLog_late.dat"
        target.write_bytes(b"opening hand")
        # Should NOT fire well before the stability gate elapses.
        assert not event.wait(timeout=0.4), "watcher fired before stability gate elapsed"
        # And should fire after the gate.
        assert event.wait(timeout=3.0), "watcher never fired after stability gate"
        assert target in seen
    finally:
        watcher.stop()


def test_wait_stable_short_circuits_for_old_mtime(tmp_path: Path) -> None:
    """Files already finalized on disk (mtime older than stability window)
    must not block startup-scan throughput by re-observing for the full
    window. Pre-fix: this test would block for ~600s. Post-fix: returns
    immediately because the file is already stable by mtime."""
    seen: list[Path] = []
    event = threading.Event()

    def on_ready(p: Path) -> None:
        seen.append(p)
        event.set()

    target = tmp_path / "Match_GameLog_old.dat"
    target.write_bytes(b"already finalized")
    old_ts = time.time() - 3600  # 1 hour ago
    os.utime(target, (old_ts, old_ts))

    watcher = LogWatcher(
        watch_dir=tmp_path,
        suffixes=frozenset({".dat"}),
        stability_seconds=600.0,
        on_file_ready=on_ready,
        name_globs=["Match_GameLog_*.dat"],
    )
    watcher.start()
    try:
        assert event.wait(timeout=5.0), "watcher did not short-circuit for finalized file"
        assert target in seen
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
