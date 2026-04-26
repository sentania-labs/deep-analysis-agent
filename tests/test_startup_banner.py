"""Tests for the startup banner + structured agent_start event emitted at boot."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from deep_analysis_agent import main as main_mod
from deep_analysis_agent.config import AppConfig
from deep_analysis_agent.first_run import CLIENT_VERSION


def _agent_start_call(log: MagicMock) -> tuple[str, dict[str, object]]:
    """Return (event, kwargs) for the structured `agent_start` log call."""
    for call in log.info.call_args_list:
        if call.args and call.args[0] == "agent_start":
            return call.args[0], call.kwargs
    raise AssertionError("agent_start event was not logged")


def test_log_startup_banner_emits_expected_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.agent_id = "agent-xyz"

    log = MagicMock()
    main_mod._log_startup_banner(cfg, log)

    event, kwargs = _agent_start_call(log)
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

    _, kwargs = _agent_start_call(log)
    assert kwargs["agent_id"] is None


def test_log_startup_banner_emits_prominent_version_line(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = AppConfig()

    log = MagicMock()
    main_mod._log_startup_banner(cfg, log)

    messages = [call.args[0] for call in log.info.call_args_list if call.args]
    # Two separator rules bracket the version line.
    rule_indices = [i for i, m in enumerate(messages) if m == main_mod._STARTUP_BANNER_RULE]
    assert len(rule_indices) >= 2
    # The "starting" line falls between two separator rules.
    starting_idx = next(i for i, m in enumerate(messages) if m == "Deep Analysis agent starting")
    assert rule_indices[0] < starting_idx < rule_indices[1]
    starting_call = log.info.call_args_list[starting_idx]
    assert starting_call.kwargs["version"] == CLIENT_VERSION
