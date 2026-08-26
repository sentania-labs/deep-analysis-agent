"""Tray notification wording for the Check for Updates flow (issue #43).

The tray must not tell the user an update will install when the updater
never launched. These tests pin both branches: success keeps the
check message, failure says the update could not be started and points
somewhere actionable.

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
    message="An update is available. It will install on next restart.",
)


def _run_check(
    monkeypatch: pytest.MonkeyPatch,
    apply_result: UpdateApplyResult,
    check_result: UpdateCheckResult = _AVAILABLE,
) -> list[str]:
    """Drive ``_check_for_updates`` and return the notification bodies."""
    monkeypatch.setattr(tray_mod, "check_for_update", lambda _v: check_result)
    monkeypatch.setattr(updater_mod, "apply_update", lambda: apply_result)

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

    final = notifications[-1]
    assert "could not be started" in final
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

    assert "could not be started" in final
    assert "Open Log" in final


def test_successful_apply_keeps_the_check_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    success = UpdateApplyResult(
        started=True,
        reason="started",
        detail="The update will install on next restart.",
        update_exe=r"C:\Users\x\AppData\Local\DeepAnalysis\Update.exe",
    )
    final = _run_check(monkeypatch, success)[-1]

    assert final == _AVAILABLE.message
    assert "could not be started" not in final


def test_no_update_available_never_calls_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def _apply() -> UpdateApplyResult:
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
    assert fake_icon.notify.call_args_list[-1].args[0] == "You're up to date (v1)."
