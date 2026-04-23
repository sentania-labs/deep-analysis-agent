"""SHA-256 hashing + SQLite-backed seen-set.

Critical ordering (v0.3.7 fix): hash first, skip if seen, yield to
caller, and only mark seen AFTER the caller has successfully
processed the file. Marking seen too early caused files to be
permanently lost on caller failure in earlier versions.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

_CHUNK = 1024 * 1024


class DedupStore:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_files (
                sha256 TEXT PRIMARY KEY,
                original_path TEXT NOT NULL,
                seen_at TEXT NOT NULL
            )
            """
        )

    def is_seen(self, sha256: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM seen_files WHERE sha256 = ?", (sha256,)
            ).fetchone()
        return row is not None

    def mark_seen(self, sha256: str, path: Path) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO seen_files (sha256, original_path, seen_at)
                VALUES (?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    original_path = excluded.original_path,
                    seen_at = excluded.seen_at
                """,
                (sha256, str(path), now),
            )

    def hash_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                h.update(chunk)
        return h.hexdigest()

    def close(self) -> None:
        with self._lock:
            self._db.close()
