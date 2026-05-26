"""Classify an MTGO match-log file as complete or inconclusive.

MTGO writes ``wins the match``, ``has conceded from the match``, or
``Match Tied`` near the end of a ``Match_GameLog_*.dat`` when the match
finishes.  If none of these signals appears in the file's tail after
the stability gate fires, we treat the file as inconclusive and let the
server's holding pen decide what to do with it.

The tail is binary-stripped the same way the server parser does
(``parser_service/parsing/parser.py`` ``_strip_binary``): only printable
ASCII (0x20..0x7E) plus newline/CR are retained, giving clean text the
regex can match against.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

Classification = Literal["complete", "inconclusive"]

_TAIL_BYTES = 64 * 1024

# Match-completion patterns — consistent with the server parser's
# _extract_match_result.  Case-insensitive to tolerate any casing
# variation in the log format.
_MATCH_COMPLETE_RE = re.compile(
    r"wins the match|has conceded from the match|Match Tied",
    re.IGNORECASE,
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

    # Strip non-printable bytes the same way the server parser does,
    # keeping only printable ASCII + newline/CR.
    cleaned = bytes(b for b in tail if 0x20 <= b <= 0x7E or b in (0x0A, 0x0D))
    text = cleaned.decode("ascii", errors="replace")
    if _MATCH_COMPLETE_RE.search(text):
        return "complete"
    return "inconclusive"
