"""Windows end-to-end proof for the installed Squirrel updater."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="requires Windows")


def _required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} was not provided by the Windows test harness")
    return Path(value)


def _drive_real_update(
    *,
    app_root: Path,
    feed: Path,
    output: Path,
) -> list[str]:
    app_exe = app_root / "app-0.0.1" / "DeepAnalysisAgent.exe"
    result = subprocess.run(
        [str(app_exe), "--updater-e2e", "--feed", str(feed), "--output", str(output)],
        cwd=app_root,
        capture_output=True,
        text=True,
        timeout=200,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    capture = json.loads(output.read_text(encoding="utf-8"))
    assert capture["completed"] is True
    assert capture["frozen"] is True
    assert Path(capture["executable"]).samefile(app_exe)
    assert capture["version"] == "0.0.1"
    assert Path(capture["update_exe"]).samefile(app_root / "Update.exe")
    notifications = capture["notifications"]
    assert isinstance(notifications, list)
    assert all(isinstance(body, str) for body in notifications)
    return notifications


def test_installed_updater_no_update_then_good_update(tmp_path: Path) -> None:
    app_root = _required_path("DAA_E2E_GOOD_APP_ROOT")
    no_update_feed = _required_path("DAA_E2E_NO_UPDATE_FEED")
    good_feed = _required_path("DAA_E2E_GOOD_FEED")

    notifications = _drive_real_update(
        app_root=app_root, feed=no_update_feed, output=tmp_path / "no-update.json"
    )
    assert notifications == ["Checking for updates…", "You're up to date (v0.0.1)."]

    notifications = _drive_real_update(
        app_root=app_root, feed=good_feed, output=tmp_path / "good.json"
    )
    target_dir = app_root / "app-0.0.2"
    assert target_dir.is_dir()
    assert not (target_dir / ".not-finished").exists()
    assert notifications == [
        "Checking for updates…",
        "Update v0.0.2 installed successfully. Restart Deep Analysis to use it.",
    ]

    notifications = _drive_real_update(
        app_root=app_root, feed=good_feed, output=tmp_path / "restart.json"
    )
    assert notifications == [
        "Checking for updates…",
        "Update v0.0.2 is installed. Restart Deep Analysis to use it.",
    ]


def test_corrupt_package_reports_failure_notification(tmp_path: Path) -> None:
    notifications = _drive_real_update(
        app_root=_required_path("DAA_E2E_CORRUPT_APP_ROOT"),
        feed=_required_path("DAA_E2E_CORRUPT_FEED"),
        output=tmp_path / "corrupt.json",
    )

    assert len(notifications) == 2
    assert "failed (exit" in notifications[-1]
    assert "will install" not in notifications[-1]


def test_stalled_update_exe_reports_fixed_timeout_notification(tmp_path: Path) -> None:
    app_root = _required_path("DAA_E2E_STALL_APP_ROOT")
    started = time.monotonic()
    notifications = _drive_real_update(
        app_root=app_root, feed=app_root, output=tmp_path / "stalled.json"
    )
    assert 120 <= time.monotonic() - started < 200
    assert notifications == [
        "Checking for updates…",
        "Update timed out after 120 seconds and may still be running. "
        "See Open Log before restarting.",
    ]
