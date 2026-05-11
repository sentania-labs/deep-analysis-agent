"""SHA-256 hashing + SQLite-backed seen-set.

Critical ordering (v0.3.7 fix): hash first, skip if seen, yield to
caller, and only mark seen AFTER the caller has successfully
processed the file. Marking seen too early caused files to be
permanently lost on caller failure in earlier versions.
"""

from __future__ import annotations

import contextlib
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
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS ix_seen_files_path ON seen_files (original_path)"
        )
        for col, col_type in [("file_size", "INTEGER"), ("file_mtime", "REAL")]:
            with contextlib.suppress(sqlite3.OperationalError):
                self._db.execute(f"ALTER TABLE seen_files ADD COLUMN {col} {col_type}")

    def is_seen(self, sha256: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM seen_files WHERE sha256 = ?", (sha256,)
            ).fetchone()
        return row is not None

    def is_path_unchanged(self, path: Path) -> bool:
        try:
            st = path.stat()
        except OSError:
            return False
        with self._lock:
            row = self._db.execute(
                "SELECT file_size, file_mtime FROM seen_files WHERE original_path = ?",
                (str(path),),
            ).fetchone()
        if row is None:
            return False
        return row[0] == st.st_size and row[1] == st.st_mtime

    def mark_seen(self, sha256: str, path: Path) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            st = path.stat()
            size, mtime = st.st_size, st.st_mtime
        except OSError:
            size, mtime = None, None
        with self._lock:
            self._db.execute(
                """
                INSERT INTO seen_files (sha256, original_path, seen_at, file_size, file_mtime)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    original_path = excluded.original_path,
                    seen_at = excluded.seen_at,
                    file_size = excluded.file_size,
                    file_mtime = excluded.file_mtime
                """,
                (sha256, str(path), now, size, mtime),
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
