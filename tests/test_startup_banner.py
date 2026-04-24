"""Tests for the agent_start structured log line emitted at boot."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from deep_analysis_agent import main as main_mod
from deep_analysis_agent.config import AppConfig
from deep_analysis_agent.first_run import CLIENT_VERSION


def test_log_startup_banner_emits_expected_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.agent_id = "agent-xyz"

    log = MagicMock()
    main_mod._log_startup_banner(cfg, log)

    log.info.assert_called_once()
    event, kwargs = log.info.call_args.args[0], log.info.call_args.kwargs
    assert event == "agent_start"
    assert kwargs["version"] == CLIENT_VERSION
    assert kwargs["agent_id"] == "agent-xyz"
    assert kwargs["server_url"] == "https://example.test"
    assert kwargs["config_path"].endswith("config.toml")
    assert kwargs["log_path"].endswith("agent.log")
    assert kwargs["log_dir"] == str(cfg.mtgo.log_dir)


def test_log_startup_banner_handles_unregistered_agent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = AppConfig()

    log = MagicMock()
    main_mod._log_startup_banner(cfg, log)

    assert log.info.call_args.kwargs["agent_id"] is None
