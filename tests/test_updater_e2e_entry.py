"""Behavior of the headless updater notification capture interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from deep_analysis_agent import main as main_mod
from deep_analysis_agent import tray, updater
from deep_analysis_agent.updater import UpdateApplyResult, UpdateCheckResult


@pytest.mark.parametrize("outcome", ["no-update", "success", "exception"])
def test_headless_entry_writes_terminal_notifications(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, outcome: str
) -> None:
    output = tmp_path / "notifications.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["DeepAnalysisAgent", "--updater-e2e", "--feed", str(tmp_path), "--output", str(output)],
    )
    monkeypatch.setattr(updater, "_UPDATE_URL", updater._UPDATE_URL)

    def check(version: str) -> UpdateCheckResult:
        assert updater._UPDATE_URL == str(tmp_path.resolve())
        if outcome == "exception":
            raise ValueError("unexpected check failure")
        return UpdateCheckResult(outcome == "success", "Already current.", "0.0.2")

    def apply(target_version: str | None = None) -> UpdateApplyResult:
        assert target_version == "0.0.2"
        return UpdateApplyResult(True, "completed", "Installed. Restart to use it.")

    monkeypatch.setattr(tray, "check_for_update", check)
    monkeypatch.setattr(updater, "apply_update", apply)
    with pytest.raises(SystemExit) as exit_info:
        main_mod.main()
    assert exit_info.value.code == 0
    capture = json.loads(output.read_text(encoding="utf-8"))
    assert capture["completed"] is True
    assert capture["executable"] == sys.executable
    expected = {
        "no-update": "Already current.",
        "success": "Installed. Restart to use it.",
        "exception": "Update check failed, see Open Log",
    }
    assert capture["notifications"] == ["Checking for updates…", expected[outcome]]
