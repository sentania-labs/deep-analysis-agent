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


def test_count_returns_correct_count(tmp_path: Path) -> None:
    db = tmp_path / "dedup.db"
    f1 = tmp_path / "a.dat"
    f2 = tmp_path / "b.dat"
    sha1 = _write(f1, b"alpha")
    sha2 = _write(f2, b"bravo")

    store = DedupStore(db)
    assert store.count() == 0
    store.mark_seen(sha1, f1)
    assert store.count() == 1
    store.mark_seen(sha2, f2)
    assert store.count() == 2


def test_clear_empties_table(tmp_path: Path) -> None:
    db = tmp_path / "dedup.db"
    f1 = tmp_path / "a.dat"
    f2 = tmp_path / "b.dat"
    sha1 = _write(f1, b"alpha")
    sha2 = _write(f2, b"bravo")

    store = DedupStore(db)
    store.mark_seen(sha1, f1)
    store.mark_seen(sha2, f2)
    assert store.count() == 2

    store.clear()
    assert store.count() == 0
    assert store.is_seen(sha1) is False
    assert store.is_seen(sha2) is False


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
