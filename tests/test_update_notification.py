"""Tray notification behavior for the Check for Updates flow.

The tray must report one truthful terminal result after its initial checking
toast, including when unexpected check or apply errors escape their helpers.

``tests/conftest.py`` holds the ingest upload contract fixtures only, so
there is nothing to reuse here; this follows the tray-test pattern in
``test_settings_window.py`` (construct a real ``TrayIcon``, stub the
pystray icon).
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from deep_analysis_agent import tray as tray_mod
from deep_analysis_agent import updater as updater_mod
from deep_analysis_agent.config import AppConfig
from deep_analysis_agent.updater import UpdateApplyResult, UpdateCheckResult

_AVAILABLE = UpdateCheckResult(
    available=True,
    message="Update v0.7.0 is available.",
    target_version="0.7.0",
)


def _run_check(
    monkeypatch: pytest.MonkeyPatch,
    apply_result: UpdateApplyResult,
    check_result: UpdateCheckResult = _AVAILABLE,
) -> list[str]:
    """Drive ``_check_for_updates`` and return the notification bodies."""
    monkeypatch.setattr(tray_mod, "check_for_update", lambda _v: check_result)
    monkeypatch.setattr(updater_mod, "apply_update", lambda **_kwargs: apply_result)

    notifications: list[str] = []
    fake_icon = MagicMock()
    fake_icon.notify.side_effect = lambda body, _title=None: notifications.append(body)

    icon = tray_mod.TrayIcon(config=AppConfig(), version="0.0.0-test")
    icon._icon = fake_icon
    icon._check_for_updates()

    for thread in threading.enumerate():
        if thread.name == "update-check":
            thread.join(timeout=10)
            assert not thread.is_alive()

    return notifications


def test_failed_apply_notifies_failure_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = UpdateApplyResult(
        started=False,
        reason="update_exe_missing",
        detail="The updater (Update.exe) was not found next to the app. "
        "Reinstall from the latest GitHub release.",
    )
    notifications = _run_check(monkeypatch, failure)

    assert len(notifications) == 2
    final = notifications[-1]
    assert "Update.exe" in final
    assert "will install on next restart" not in final
    # The user is pointed somewhere actionable, not just told "failed".
    assert "GitHub release" in final


def test_failed_launch_mentions_the_log(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = UpdateApplyResult(
        started=False,
        reason="launch_failed",
        detail="The updater would not launch. Use Open Log for the error, "
        "or install the latest GitHub release manually.",
        update_exe=r"C:\Users\x\AppData\Local\DeepAnalysis\Update.exe",
    )
    final = _run_check(monkeypatch, failure)[-1]

    assert "would not launch" in final
    assert "Open Log" in final


def test_successful_apply_keeps_the_check_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    success = UpdateApplyResult(
        started=True,
        reason="completed",
        detail="Update installed successfully. Restart Deep Analysis to use it.",
        update_exe=r"C:\Users\x\AppData\Local\DeepAnalysis\Update.exe",
        exit_code=0,
    )
    notifications = _run_check(monkeypatch, success)
    final = notifications[-1]

    assert len(notifications) == 2
    assert final == success.detail
    assert "installed successfully" in final


def test_tray_passes_configured_timeout_and_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []
    success = UpdateApplyResult(
        started=True,
        reason="completed",
        detail="Update v0.7.0 installed successfully. Restart Deep Analysis to use it.",
        exit_code=0,
        target_version="0.7.0",
    )
    monkeypatch.setattr(tray_mod, "check_for_update", lambda _v: _AVAILABLE)

    def _apply(**kwargs: Any) -> UpdateApplyResult:
        seen.append(kwargs)
        return success

    monkeypatch.setattr(updater_mod, "apply_update", _apply)
    config = AppConfig()
    config.agent.update_timeout_seconds = 275
    fake_icon = MagicMock()
    icon = tray_mod.TrayIcon(config=config, version="0.6.3")
    icon._icon = fake_icon

    icon._check_for_updates()
    for thread in threading.enumerate():
        if thread.name == "update-check":
            thread.join(timeout=10)
            assert not thread.is_alive()

    assert seen == [{"timeout_seconds": 275, "target_version": "0.7.0"}]


def test_no_update_available_never_calls_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def _apply(**_kwargs: Any) -> UpdateApplyResult:
        calls.append(1)
        return UpdateApplyResult(started=False, reason="x", detail="y")

    monkeypatch.setattr(updater_mod, "apply_update", _apply)
    monkeypatch.setattr(
        tray_mod,
        "check_for_update",
        lambda _v: UpdateCheckResult(available=False, message="You're up to date (v1)."),
    )

    fake_icon = MagicMock()
    icon = tray_mod.TrayIcon(config=AppConfig(), version="0.0.0-test")
    icon._icon = fake_icon
    icon._check_for_updates()
    for thread in threading.enumerate():
        if thread.name == "update-check":
            thread.join(timeout=10)

    assert calls == []
    assert fake_icon.notify.call_count == 2
    assert fake_icon.notify.call_args_list[-1].args[0] == "You're up to date (v1)."


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            UpdateApplyResult(
                started=False,
                reason="exit_nonzero",
                detail="Update failed (exit 17). See Open Log for details.",
                exit_code=17,
            ),
            "exit 17",
        ),
        (
            UpdateApplyResult(
                started=False,
                reason="timeout",
                detail="Update timed out after 30 seconds and may still be running.",
            ),
            "timed out",
        ),
    ],
)
def test_apply_outcome_has_one_truthful_terminal_notification(
    monkeypatch: pytest.MonkeyPatch,
    failure: UpdateApplyResult,
    expected: str,
) -> None:
    notifications = _run_check(monkeypatch, failure)

    assert len(notifications) == 2
    assert expected in notifications[-1]
    assert "will install" not in notifications[-1]


def test_unexpected_check_error_has_one_terminal_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(_version: str) -> UpdateCheckResult:
        raise ValueError("bad updater state")

    monkeypatch.setattr(tray_mod, "check_for_update", _raise)
    notifications: list[str] = []
    fake_icon = MagicMock()
    fake_icon.notify.side_effect = lambda body, _title=None: notifications.append(body)
    icon = tray_mod.TrayIcon(config=AppConfig(), version="0.0.0-test")
    icon._icon = fake_icon

    icon._check_for_updates()
    for thread in threading.enumerate():
        if thread.name == "update-check":
            thread.join(timeout=10)
            assert not thread.is_alive()

    assert notifications == ["Checking for updates…", "Update check failed, see Open Log"]


def test_unexpected_apply_error_has_one_terminal_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tray_mod, "check_for_update", lambda _version: _AVAILABLE)

    def _raise(**_kwargs: Any) -> UpdateApplyResult:
        raise ValueError("bad process state")

    monkeypatch.setattr(updater_mod, "apply_update", _raise)
    notifications: list[str] = []
    fake_icon = MagicMock()
    fake_icon.notify.side_effect = lambda body, _title=None: notifications.append(body)
    icon = tray_mod.TrayIcon(config=AppConfig(), version="0.0.0-test")
    icon._icon = fake_icon

    icon._check_for_updates()
    for thread in threading.enumerate():
        if thread.name == "update-check":
            thread.join(timeout=10)
            assert not thread.is_alive()

    assert notifications == ["Checking for updates…", "Update check failed, see Open Log"]
