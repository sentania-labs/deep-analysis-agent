"""Classify an MTGO match-log file as complete or inconclusive.

MTGO writes `wins the match` or `has conceded from the match` near the
end of a `Match_GameLog_*.dat` when the match finishes. If neither
appears in the file's tail after the stability gate fires, we treat
the file as inconclusive and let the server's holding pen decide what
to do with it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

Classification = Literal["complete", "inconclusive"]

_TAIL_BYTES = 64 * 1024
_FINALIZED_MARKERS: tuple[bytes, ...] = (
    b"wins the match",
    b"has conceded from the match",
)


def classify_match(path: Path, tail_bytes: int = _TAIL_BYTES) -> Classification:
    """Return ``"complete"`` if the file tail shows a finalized match signal."""
    try:
        with path.open("rb") as fh:
            try:
                fh.seek(-tail_bytes, 2)
            except OSError:
                fh.seek(0)
            tail = fh.read()
    except OSError:
        return "inconclusive"

    lowered = tail.lower()
    for marker in _FINALIZED_MARKERS:
        if marker in lowered:
            return "complete"
    return "inconclusive"
