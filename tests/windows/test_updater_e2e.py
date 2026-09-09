"""Windows end-to-end proof for the installed Squirrel updater."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deep_analysis_agent import tray as tray_mod
from deep_analysis_agent import updater as updater_mod
from deep_analysis_agent.config import AppConfig
from deep_analysis_agent.paths import squirrel_update_exe
from deep_analysis_agent.updater import UpdateCheckResult

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="requires Windows")


def _required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} was not provided by the Windows test harness")
    return Path(value)


def _drive_real_update(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_root: Path,
    feed: Path,
    running_version: str = "0.0.1",
    check_result: UpdateCheckResult | None = None,
) -> list[str]:
    app_exe = app_root / f"app-{running_version}" / "DeepAnalysisAgent.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_exe))
    monkeypatch.setattr(updater_mod, "_UPDATE_URL", str(feed))
    if check_result is not None:
        monkeypatch.setattr(tray_mod, "check_for_update", lambda _version: check_result)

    notifications: list[str] = []
    fake_icon = MagicMock()
    fake_icon.notify.side_effect = lambda body, _title=None: notifications.append(body)
    icon = tray_mod.TrayIcon(config=AppConfig(), version=running_version)
    icon._icon = fake_icon

    previous_threads = set(threading.enumerate())
    icon._check_for_updates()
    update_threads = [
        thread
        for thread in threading.enumerate()
        if thread.name == "update-check" and thread not in previous_threads
    ]
    assert len(update_threads) == 1
    update_threads[0].join(timeout=150)
    assert not update_threads[0].is_alive()
    return notifications


def test_installed_updater_no_update_then_good_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_root = _required_path("DAA_E2E_GOOD_APP_ROOT")
    no_update_feed = _required_path("DAA_E2E_NO_UPDATE_FEED")
    good_feed = _required_path("DAA_E2E_GOOD_FEED")

    with monkeypatch.context() as context:
        notifications = _drive_real_update(
            context,
            app_root=app_root,
            feed=no_update_feed,
        )
    assert notifications == ["Checking for updates…", "You're up to date (v0.0.1)."]

    with monkeypatch.context() as context:
        context.setattr(sys, "frozen", True, raising=False)
        context.setattr(
            sys,
            "executable",
            str(app_root / "app-0.0.1" / "DeepAnalysisAgent.exe"),
        )
        assert squirrel_update_exe() == app_root / "Update.exe"

    with monkeypatch.context() as context:
        notifications = _drive_real_update(
            context,
            app_root=app_root,
            feed=good_feed,
        )
    target_dir = app_root / "app-0.0.2"
    assert target_dir.is_dir()
    assert not (target_dir / ".not-finished").exists()
    assert notifications == [
        "Checking for updates…",
        "Update v0.0.2 installed successfully. Restart Deep Analysis to use it.",
    ]

    with monkeypatch.context() as context:
        notifications = _drive_real_update(
            context,
            app_root=app_root,
            feed=good_feed,
        )
    assert notifications == [
        "Checking for updates…",
        "Update v0.0.2 is installed. Restart Deep Analysis to use it.",
    ]


def test_corrupt_package_reports_failure_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications = _drive_real_update(
        monkeypatch,
        app_root=_required_path("DAA_E2E_CORRUPT_APP_ROOT"),
        feed=_required_path("DAA_E2E_CORRUPT_FEED"),
    )

    assert len(notifications) == 2
    assert "failed (exit" in notifications[-1]
    assert "will install" not in notifications[-1]


def test_stalled_update_exe_reports_fixed_timeout_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_root = _required_path("DAA_E2E_STALL_APP_ROOT")
    available = UpdateCheckResult(
        available=True,
        message="Update v0.0.2 is available.",
        target_version="0.0.2",
    )
    assert updater_mod._APPLY_TIMEOUT == 120
    monkeypatch.setattr(updater_mod, "_APPLY_TIMEOUT", 1)

    notifications = _drive_real_update(
        monkeypatch,
        app_root=app_root,
        feed=app_root,
        check_result=available,
    )
    assert notifications == [
        "Checking for updates…",
        "Update timed out after 1 seconds and may still be running. "
        "See Open Log before restarting.",
    ]
    assert "will install" not in notifications[-1]
