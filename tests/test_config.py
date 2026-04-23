"""Tests for AppConfig loading + env overrides."""

from __future__ import annotations

from pathlib import Path

from deep_analysis_agent.config import AppConfig, load_config
from deep_analysis_agent.paths import config_path


def test_defaults_load_without_config_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = AppConfig()
    assert cfg.mtgo.stability_seconds == 5.0
    assert cfg.server.tls_verify is True
    assert cfg.logging.level == "INFO"
    assert ".dat" in cfg.mtgo.watched_suffixes


def test_env_override_nested(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("DEEP_ANALYSIS_MTGO__LOG_DIR", "/tmp/test-log-dir")
    monkeypatch.setenv("DEEP_ANALYSIS_LOGGING__LEVEL", "DEBUG")
    cfg = AppConfig()
    assert cfg.mtgo.log_dir == Path("/tmp/test-log-dir")
    assert cfg.logging.level == "DEBUG"


def test_config_path_returns_sensible_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    p = config_path()
    assert p.name == "config.toml"
    assert "DeepAnalysis" in str(p)


def test_load_config_creates_app_data_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    load_config()
    assert (tmp_path / "DeepAnalysis").is_dir()
