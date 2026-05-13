"""Unit tests for version-change detection and marker consumption logic."""

from __future__ import annotations

from pathlib import Path

import pytest
import structlog

from deep_analysis_agent import __version__
from deep_analysis_agent.main import (
    _LAST_VERSION_FILE,
    _MARKER_FIRST_RUN,
    _MARKER_JUST_UPDATED,
    _check_version_upgrade,
    _consume_marker,
)


@pytest.fixture
def data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr("deep_analysis_agent.main.app_data_dir", lambda: tmp_path)
    return tmp_path


# --- _check_version_upgrade ---


def test_first_run_no_previous_version(data_dir: Path) -> None:
    log = structlog.get_logger("test")
    result = _check_version_upgrade(log)
    assert result is None
    # Should have written current version.
    assert (data_dir / _LAST_VERSION_FILE).read_text(encoding="utf-8") == __version__


def test_same_version_returns_none(data_dir: Path) -> None:
    (data_dir / _LAST_VERSION_FILE).write_text(__version__, encoding="utf-8")
    log = structlog.get_logger("test")
    result = _check_version_upgrade(log)
    assert result is None


def test_upgrade_detected(data_dir: Path) -> None:
    (data_dir / _LAST_VERSION_FILE).write_text("0.0.1", encoding="utf-8")
    log = structlog.get_logger("test")
    result = _check_version_upgrade(log)
    assert result == "0.0.1"
    # Version file updated to current.
    assert (data_dir / _LAST_VERSION_FILE).read_text(encoding="utf-8") == __version__


def test_downgrade_detected(data_dir: Path) -> None:
    """A downgrade is still a version change — should return the previous."""
    (data_dir / _LAST_VERSION_FILE).write_text("99.99.99", encoding="utf-8")
    log = structlog.get_logger("test")
    result = _check_version_upgrade(log)
    assert result == "99.99.99"


# --- _consume_marker ---


def test_consume_marker_present(data_dir: Path) -> None:
    marker = data_dir / _MARKER_JUST_UPDATED
    marker.write_text("0.4.16", encoding="utf-8")
    result = _consume_marker(_MARKER_JUST_UPDATED)
    assert result == "0.4.16"
    assert not marker.exists()


def test_consume_marker_absent(data_dir: Path) -> None:
    result = _consume_marker(_MARKER_JUST_UPDATED)
    assert result is None


def test_consume_marker_empty_content(data_dir: Path) -> None:
    marker = data_dir / _MARKER_FIRST_RUN
    marker.write_text("", encoding="utf-8")
    result = _consume_marker(_MARKER_FIRST_RUN)
    # Empty content should return "unknown", not empty string.
    assert result == "unknown"
    assert not marker.exists()
