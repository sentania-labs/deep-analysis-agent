"""Unit tests for Squirrel.Windows lifecycle hook handling in main.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from deep_analysis_agent.main import (
    _MARKER_FIRST_RUN,
    _MARKER_JUST_UPDATED,
    _handle_squirrel_hooks,
    _write_marker,
)


@pytest.mark.parametrize(
    "hook",
    [
        "--squirrel-install",
        "--squirrel-updated",
        "--squirrel-obsolete",
        "--squirrel-uninstall",
    ],
)
def test_squirrel_hook_recognized(monkeypatch: pytest.MonkeyPatch, hook: str) -> None:
    monkeypatch.setattr(sys, "argv", ["DeepAnalysisAgent.exe", hook])
    # Prevent actual marker writes during hook tests.
    monkeypatch.setattr("deep_analysis_agent.main._write_marker", lambda name: None)
    assert _handle_squirrel_hooks() is True


def test_no_arg_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["DeepAnalysisAgent.exe"])
    assert _handle_squirrel_hooks() is False


def test_unknown_arg_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["DeepAnalysisAgent.exe", "--some-other-flag"])
    assert _handle_squirrel_hooks() is False


def test_squirrel_updated_writes_marker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["DeepAnalysisAgent.exe", "--squirrel-updated"])
    monkeypatch.setattr("deep_analysis_agent.main.app_data_dir", lambda: tmp_path)
    assert _handle_squirrel_hooks() is True
    marker = tmp_path / _MARKER_JUST_UPDATED
    assert marker.exists()
    assert marker.read_text(encoding="utf-8")  # contains version string


def test_squirrel_install_writes_marker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["DeepAnalysisAgent.exe", "--squirrel-install"])
    monkeypatch.setattr("deep_analysis_agent.main.app_data_dir", lambda: tmp_path)
    assert _handle_squirrel_hooks() is True
    marker = tmp_path / _MARKER_FIRST_RUN
    assert marker.exists()


def test_squirrel_obsolete_no_marker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["DeepAnalysisAgent.exe", "--squirrel-obsolete"])
    monkeypatch.setattr("deep_analysis_agent.main.app_data_dir", lambda: tmp_path)
    assert _handle_squirrel_hooks() is True
    # obsolete should not write any marker
    assert not (tmp_path / _MARKER_JUST_UPDATED).exists()
    assert not (tmp_path / _MARKER_FIRST_RUN).exists()


def test_write_marker_creates_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("deep_analysis_agent.main.app_data_dir", lambda: tmp_path)
    _write_marker("test_marker")
    assert (tmp_path / "test_marker").exists()


def test_write_marker_creates_parent_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "dir"
    monkeypatch.setattr("deep_analysis_agent.main.app_data_dir", lambda: nested)
    _write_marker("test_marker")
    assert (nested / "test_marker").exists()
