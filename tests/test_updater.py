"""Tests for the updater module."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from deep_analysis_agent.updater import (
    UpdateCheckResult,
    apply_update,
    check_for_update,
)


def test_check_returns_unavailable_when_not_frozen() -> None:
    with patch.object(sys, "frozen", False, create=True):
        result = check_for_update("0.4.9")
    assert result.available is False
    assert "dev build" in result.message


def test_update_check_result_dataclass() -> None:
    r = UpdateCheckResult(available=True, message="v0.5.0 available")
    assert r.available is True
    assert r.message == "v0.5.0 available"


def test_apply_update_reports_missing_update_exe() -> None:
    with patch("deep_analysis_agent.updater._find_update_exe", return_value=None):
        result = apply_update()
    assert bool(result) is False
    assert result.started is False
    assert result.reason == "update_exe_missing"
    assert result.update_exe is None
    assert "Update.exe" in result.detail


def test_apply_update_reports_launch_failure(tmp_path: Path) -> None:
    fake_exe = tmp_path / "Update.exe"
    fake_exe.write_text("stub", encoding="utf-8")
    with (
        patch("deep_analysis_agent.updater._find_update_exe", return_value=fake_exe),
        patch("subprocess.Popen", side_effect=OSError("boom")),
    ):
        result = apply_update()
    assert bool(result) is False
    assert result.reason == "launch_failed"
    assert result.update_exe == str(fake_exe)
    assert "Open Log" in result.detail


def test_apply_update_success_carries_resolved_path(tmp_path: Path) -> None:
    fake_exe = tmp_path / "Update.exe"
    fake_exe.write_text("stub", encoding="utf-8")
    with (
        patch("deep_analysis_agent.updater._find_update_exe", return_value=fake_exe),
        patch("subprocess.Popen") as popen,
    ):
        result = apply_update()
    assert bool(result) is True
    assert result.reason == "started"
    assert result.update_exe == str(fake_exe)
    assert str(fake_exe) in popen.call_args.args[0][0]


def test_apply_update_logs_resolved_path_and_reason(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    fake_exe = tmp_path / "Update.exe"
    fake_exe.write_text("stub", encoding="utf-8")
    with (
        caplog.at_level(logging.ERROR, logger="deep_analysis_agent.updater"),
        patch("deep_analysis_agent.updater._find_update_exe", return_value=fake_exe),
        patch("subprocess.Popen", side_effect=OSError("boom")),
    ):
        apply_update()
    logged = caplog.text
    assert "reason=launch_failed" in logged
    assert str(fake_exe) in logged
