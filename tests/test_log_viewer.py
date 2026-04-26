"""Tests for the in-app LogViewerWindow."""

from __future__ import annotations

from pathlib import Path

from deep_analysis_agent.log_viewer import (
    LEVELS,
    LogViewerWindow,
    filter_lines,
)

SAMPLE_LOG = (
    "2026-04-26 09:00:00,123 INFO deep_analysis_agent.main: agent_start version=0.4.2\n"
    "2026-04-26 09:00:01,456 DEBUG deep_analysis_agent.shipper: file_seen path=/tmp/x\n"
    "2026-04-26 09:00:02,789 WARNING deep_analysis_agent.tray: cycle skip\n"
    "2026-04-26 09:00:03,012 ERROR deep_analysis_agent.shipper: upload_failed\n"
    "2026-04-26 09:00:04,345 INFO deep_analysis_agent.heartbeat: ping ok\n"
)


def test_levels_constant_includes_all_and_canonical_levels() -> None:
    assert LEVELS[0] == "All"
    for expected in ("DEBUG", "INFO", "WARNING", "ERROR"):
        assert expected in LEVELS


def test_filter_lines_all_returns_input_unchanged() -> None:
    assert filter_lines(SAMPLE_LOG, "All") == SAMPLE_LOG


def test_filter_lines_info_keeps_only_info_lines() -> None:
    out = filter_lines(SAMPLE_LOG, "INFO")
    assert "agent_start" in out
    assert "ping ok" in out
    assert "DEBUG" not in out
    assert "WARNING" not in out
    assert "ERROR" not in out


def test_filter_lines_error_keeps_single_error_line() -> None:
    out = filter_lines(SAMPLE_LOG, "ERROR")
    assert out.count("\n") == 1
    assert "upload_failed" in out


def test_filter_lines_unknown_level_returns_empty_string() -> None:
    assert filter_lines(SAMPLE_LOG, "TRACE") == ""


def test_filter_lines_empty_content_passes_through() -> None:
    assert filter_lines("", "ERROR") == ""


def test_log_viewer_constructs_without_starting_thread(tmp_path: Path) -> None:
    log_file = tmp_path / "agent.log"
    viewer = LogViewerWindow(log_file, on_close=lambda: None)
    assert viewer._thread is None
    assert viewer._root is None
    assert viewer._log_file == log_file


def test_log_viewer_accepts_none_log_file() -> None:
    viewer = LogViewerWindow(None)
    assert viewer._log_file is None


def test_log_viewer_close_is_noop_when_root_unset() -> None:
    viewer = LogViewerWindow(None)
    viewer.close()
