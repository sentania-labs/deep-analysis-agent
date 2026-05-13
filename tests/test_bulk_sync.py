"""Tests for bulk startup sync (watcher + dedup integration)."""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from deep_analysis_agent.dedup import DedupStore
from deep_analysis_agent.watcher import LogWatcher


def _write(path: Path, content: bytes) -> str:
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def test_startup_scan_skips_known_unchanged_files(tmp_path: Path) -> None:
    """Files already in dedup DB with matching size/mtime are not queued."""
    db = DedupStore(tmp_path / "dedup.db")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    old = log_dir / "Match_GameLog_old.dat"
    sha = _write(old, b"old content")
    db.mark_seen(sha, old)

    seen: list[Path] = []

    watcher = LogWatcher(
        watch_dir=log_dir,
        suffixes=frozenset({".dat"}),
        stability_seconds=0.2,
        on_file_ready=seen.append,
        name_glob="Match_GameLog_*.dat",
        dedup=db,
    )
    watcher.start()
    time.sleep(0.8)
    watcher.stop()

    assert old not in seen


def test_startup_scan_queues_new_files(tmp_path: Path) -> None:
    """Files not in dedup DB are queued."""
    db = DedupStore(tmp_path / "dedup.db")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    new = log_dir / "Match_GameLog_new.dat"
    _write(new, b"new content")

    seen: list[Path] = []
    event = threading.Event()

    def on_ready(p: Path) -> None:
        seen.append(p)
        event.set()

    watcher = LogWatcher(
        watch_dir=log_dir,
        suffixes=frozenset({".dat"}),
        stability_seconds=0.2,
        on_file_ready=on_ready,
        name_glob="Match_GameLog_*.dat",
        dedup=db,
    )
    watcher.start()
    assert event.wait(timeout=3.0), "new file was not queued"
    watcher.stop()

    assert new in seen


def test_startup_scan_queues_changed_files(tmp_path: Path) -> None:
    """Files in dedup DB but with different size/mtime are queued."""
    db = DedupStore(tmp_path / "dedup.db")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    f = log_dir / "Match_GameLog_changed.dat"
    sha = _write(f, b"original")
    db.mark_seen(sha, f)

    time.sleep(0.05)
    _write(f, b"modified content that is different")

    seen: list[Path] = []
    event = threading.Event()

    def on_ready(p: Path) -> None:
        seen.append(p)
        event.set()

    watcher = LogWatcher(
        watch_dir=log_dir,
        suffixes=frozenset({".dat"}),
        stability_seconds=0.2,
        on_file_ready=on_ready,
        name_glob="Match_GameLog_*.dat",
        dedup=db,
    )
    watcher.start()
    assert event.wait(timeout=3.0), "changed file was not queued"
    watcher.stop()

    assert f in seen


def test_known_paths_returns_all_entries(tmp_path: Path) -> None:
    db = DedupStore(tmp_path / "dedup.db")
    f1 = tmp_path / "a.dat"
    f2 = tmp_path / "b.dat"
    sha1 = _write(f1, b"aaa")
    sha2 = _write(f2, b"bbb")
    db.mark_seen(sha1, f1)
    db.mark_seen(sha2, f2)

    known = db.known_paths()
    assert str(f1) in known
    assert str(f2) in known
    assert known[str(f1)][0] == 3  # size


def test_startup_scan_skips_relocated_files_by_hash(tmp_path: Path) -> None:
    """Files at a new path but with a known hash are skipped via rehash."""
    db = DedupStore(tmp_path / "dedup.db")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    content = b"match log data"
    sha = hashlib.sha256(content).hexdigest()

    # Mark as seen at the OLD path (simulates ClickOnce directory rotation).
    old_path = tmp_path / "old_dir" / "Match_GameLog_abc.dat"
    old_path.parent.mkdir()
    _write(old_path, content)
    db.mark_seen(sha, old_path)

    # File now lives at a NEW path with identical content.
    new_path = log_dir / "Match_GameLog_abc.dat"
    _write(new_path, content)

    seen: list[Path] = []

    watcher = LogWatcher(
        watch_dir=log_dir,
        suffixes=frozenset({".dat"}),
        stability_seconds=0.2,
        on_file_ready=seen.append,
        name_glob="Match_GameLog_*.dat",
        dedup=db,
    )
    watcher.start()
    time.sleep(0.8)
    watcher.stop()

    assert new_path not in seen

    # Dedup DB should now have the updated path.
    known = db.known_paths()
    assert str(new_path) in known
