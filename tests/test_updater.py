"""Tests for the updater module."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deep_analysis_agent.paths import squirrel_update_exe
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


def test_squirrel_update_exe_returns_none_when_not_frozen() -> None:
    with patch.object(sys, "frozen", False, create=True):
        assert squirrel_update_exe() is None


def test_squirrel_update_exe_finds_parent_of_frozen_app(tmp_path: Path) -> None:
    app_dir = tmp_path / "app-0.7.0"
    app_dir.mkdir()
    app_exe = app_dir / "DeepAnalysisAgent.exe"
    app_exe.write_text("stub", encoding="utf-8")
    update_exe = tmp_path / "Update.exe"
    update_exe.write_text("stub", encoding="utf-8")

    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", str(app_exe)),
    ):
        assert squirrel_update_exe() == update_exe


def test_check_parses_target_version_after_progress_lines(tmp_path: Path) -> None:
    fake_exe = tmp_path / "Update.exe"
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=(
            '33\n100\n{"currentVersion":"0.4.9","futureVersion":"0.5.0",'
            '"releasesToApply":[{"version":"0.5.0"}]}\n'
        ),
        stderr="",
    )
    with (
        patch("deep_analysis_agent.updater._find_update_exe", return_value=fake_exe),
        patch("subprocess.run", return_value=completed),
    ):
        result = check_for_update("0.4.9")

    assert result.available is True
    assert result.target_version == "0.5.0"
    assert result.message == "Update v0.5.0 is available."


def test_check_json_with_no_releases_is_up_to_date(tmp_path: Path) -> None:
    fake_exe = tmp_path / "Update.exe"
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=('{"currentVersion":"0.4.9","futureVersion":"0.4.9","releasesToApply":[]}\n'),
        stderr="",
    )
    with (
        patch("deep_analysis_agent.updater._find_update_exe", return_value=fake_exe),
        patch("subprocess.run", return_value=completed),
    ):
        result = check_for_update("0.4.9")

    assert result.available is False
    assert result.target_version is None
    assert result.message == "You're up to date (v0.4.9)."


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
    (tmp_path / "app-0.7.0").mkdir()
    with (
        patch("deep_analysis_agent.updater._find_update_exe", return_value=fake_exe),
        patch("subprocess.Popen") as popen,
    ):
        popen.return_value.wait.return_value = 0
        result = apply_update(target_version="0.7.0")
    assert bool(result) is True
    assert result.reason == "completed"
    assert result.exit_code == 0
    assert result.target_version == "0.7.0"
    assert result.update_exe == str(fake_exe)
    assert str(fake_exe) in popen.call_args.args[0][0]
    popen.return_value.wait.assert_called_once_with(timeout=120)


def test_apply_update_rejects_zero_exit_without_target_install(tmp_path: Path) -> None:
    fake_exe = tmp_path / "Update.exe"
    child = MagicMock()
    child.wait.return_value = 0
    with (
        patch("deep_analysis_agent.updater._find_update_exe", return_value=fake_exe),
        patch("subprocess.Popen", return_value=child),
    ):
        result = apply_update(target_version="0.7.0")

    assert result.started is False
    assert result.reason == "target_not_installed"
    assert result.exit_code == 0
    assert result.target_version == "0.7.0"
    assert "was not installed" in result.detail


def test_apply_update_rejects_incomplete_target_install(tmp_path: Path) -> None:
    fake_exe = tmp_path / "Update.exe"
    target_dir = tmp_path / "app-0.7.0"
    target_dir.mkdir()
    (target_dir / ".not-finished").write_text("", encoding="utf-8")
    child = MagicMock()
    child.wait.return_value = 0
    with (
        patch("deep_analysis_agent.updater._find_update_exe", return_value=fake_exe),
        patch("subprocess.Popen", return_value=child),
    ):
        result = apply_update(target_version="0.7.0")

    assert result.started is False
    assert result.reason == "target_not_installed"


def test_apply_update_reports_nonzero_exit(tmp_path: Path) -> None:
    fake_exe = tmp_path / "Update.exe"
    child = MagicMock()
    child.wait.return_value = 23
    with (
        patch("deep_analysis_agent.updater._find_update_exe", return_value=fake_exe),
        patch("subprocess.Popen", return_value=child),
    ):
        result = apply_update(timeout_seconds=45)

    assert result.started is False
    assert result.reason == "exit_nonzero"
    assert result.exit_code == 23
    assert "exit 23" in result.detail
    child.wait.assert_called_once_with(timeout=45)


def test_apply_update_reports_timeout(tmp_path: Path) -> None:
    fake_exe = tmp_path / "Update.exe"
    child = MagicMock()
    child.wait.side_effect = subprocess.TimeoutExpired(cmd="Update.exe", timeout=9)
    with (
        patch("deep_analysis_agent.updater._find_update_exe", return_value=fake_exe),
        patch("subprocess.Popen", return_value=child),
    ):
        result = apply_update(timeout_seconds=9)

    assert result.started is False
    assert result.reason == "timeout"
    assert result.exit_code is None
    assert "9 seconds" in result.detail
    assert "may still be running" in result.detail


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
