"""Tests for the dedup store + hash-before-mark ordering."""

from __future__ import annotations

import hashlib
from pathlib import Path

from deep_analysis_agent.dedup import DedupStore


def _write(path: Path, content: bytes) -> str:
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def test_hash_file_matches_sha256(tmp_path: Path) -> None:
    f = tmp_path / "x.dat"
    expected = _write(f, b"hello world")
    store = DedupStore(tmp_path / "dedup.db")
    assert store.hash_file(f) == expected


def test_is_seen_false_for_unknown(tmp_path: Path) -> None:
    store = DedupStore(tmp_path / "dedup.db")
    assert store.is_seen("deadbeef") is False


def test_persistence_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "dedup.db"
    f = tmp_path / "x.dat"
    sha = _write(f, b"payload")

    s1 = DedupStore(db)
    s1.mark_seen(sha, f)
    s1.close()

    s2 = DedupStore(db)
    assert s2.is_seen(sha) is True


def test_hash_computed_before_mark_seen(tmp_path: Path) -> None:
    """The caller must be able to hash, check is_seen, then decide to
    mark_seen only after success. Simulate a 'failed' flow: hash, check,
    skip mark_seen. A fresh store must still see the file as unseen."""
    db = tmp_path / "dedup.db"
    f = tmp_path / "x.dat"
    sha = _write(f, b"not-yet-processed")

    store = DedupStore(db)
    sha_computed = store.hash_file(f)
    assert sha_computed == sha
    assert store.is_seen(sha_computed) is False
    # caller 'fails' here — do NOT mark_seen
    store.close()

    s2 = DedupStore(db)
    assert s2.is_seen(sha) is False  # still unseen — ready for retry
