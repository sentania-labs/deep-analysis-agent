"""Tests for the tail-scan match-classifier."""

from __future__ import annotations

from pathlib import Path

from deep_analysis_agent.match_classifier import classify_match


def test_classify_complete_on_wins_the_match(tmp_path: Path) -> None:
    p = tmp_path / "Match_GameLog_1.dat"
    p.write_bytes(b"...lots of turns...\nAlice wins the match\n")
    assert classify_match(p) == "complete"


def test_classify_complete_on_concede(tmp_path: Path) -> None:
    p = tmp_path / "Match_GameLog_2.dat"
    p.write_bytes(b"...turn 9...\nBob has conceded from the match\n")
    assert classify_match(p) == "complete"


def test_classify_complete_case_insensitive(tmp_path: Path) -> None:
    """MTGO casing varies — markers compare case-insensitively."""
    p = tmp_path / "Match_GameLog_3.dat"
    p.write_bytes(b"Player Wins The Match.")
    assert classify_match(p) == "complete"


def test_classify_inconclusive_when_no_marker(tmp_path: Path) -> None:
    p = tmp_path / "Match_GameLog_4.dat"
    p.write_bytes(b"opening hands\nturn 1\nturn 2\n... mid-game ...")
    assert classify_match(p) == "inconclusive"


def test_classify_inconclusive_on_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "Match_GameLog_empty.dat"
    p.write_bytes(b"")
    assert classify_match(p) == "inconclusive"


def test_classify_marker_in_last_tail_window(tmp_path: Path) -> None:
    """Marker sitting in the final tail_bytes of a large file is detected."""
    p = tmp_path / "Match_GameLog_5.dat"
    padding = b"A" * (256 * 1024)
    p.write_bytes(padding + b"\nfinal line: wins the match\n")
    assert classify_match(p) == "complete"


def test_classify_marker_outside_tail_window_is_inconclusive(tmp_path: Path) -> None:
    """Marker earlier than tail_bytes from EOF is intentionally NOT seen.

    Real MTGO match-end strings sit at the very end of the file. If the
    marker is only present in the early game (impossible in real data),
    the tail-scan would miss it — that's by design (cheap + bounded).
    """
    p = tmp_path / "Match_GameLog_6.dat"
    early = b"wins the match" + b"X" * (128 * 1024)
    p.write_bytes(early)
    assert classify_match(p, tail_bytes=4096) == "inconclusive"


def test_classify_missing_file_inconclusive(tmp_path: Path) -> None:
    p = tmp_path / "does_not_exist.dat"
    assert classify_match(p) == "inconclusive"


def test_classify_binary_noise_inconclusive(tmp_path: Path) -> None:
    """Random bytes that don't contain the markers classify as inconclusive."""
    p = tmp_path / "Match_GameLog_7.dat"
    p.write_bytes(bytes(range(256)) * 16)
    assert classify_match(p) == "inconclusive"
