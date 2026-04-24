"""Tests for AppConfig loading + env overrides."""

from __future__ import annotations

from pathlib import Path

import pytest

from deep_analysis_agent import config as config_module
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


def test_default_mtgo_log_dir_uses_localappdata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = AppConfig()
    assert cfg.mtgo.log_dir == tmp_path / "Apps" / "2.0"


def test_default_mtgo_log_dir_fallback_without_localappdata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = AppConfig()
    assert cfg.mtgo.log_dir == tmp_path / "AppData" / "Local" / "Apps" / "2.0"


def test_logging_format_defaults_to_plaintext(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = AppConfig()
    assert cfg.logging.format == "plaintext"


def test_logging_format_parses_json_from_toml(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app_dir = tmp_path / "DeepAnalysis"
    app_dir.mkdir(parents=True)
    (app_dir / "config.toml").write_text(
        '[logging]\nformat = "json"\nlevel = "DEBUG"\n',
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.logging.format == "json"
    assert cfg.logging.level == "DEBUG"


def test_logging_format_parses_plaintext_explicitly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app_dir = tmp_path / "DeepAnalysis"
    app_dir.mkdir(parents=True)
    (app_dir / "config.toml").write_text(
        '[logging]\nformat = "plaintext"\n',
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.logging.format == "plaintext"


def test_logging_format_missing_uses_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app_dir = tmp_path / "DeepAnalysis"
    app_dir.mkdir(parents=True)
    (app_dir / "config.toml").write_text(
        '[logging]\nlevel = "INFO"\n',
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.logging.format == "plaintext"


def test_config_migration_rewrites_stale_default_user_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loading a config with a Users\\Default\\... MTGO path rewrites it to the current default."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app_dir = tmp_path / "DeepAnalysis"
    app_dir.mkdir(parents=True)
    # TOML literal string (single quotes) — backslashes are not escape sequences.
    (app_dir / "config.toml").write_text(
        "[mtgo]\nlog_dir = 'C:\\Users\\Default\\AppData\\Local\\Apps\\2.0\\MTGO'\n",
        encoding="utf-8",
    )

    saved: list[AppConfig] = []
    monkeypatch.setattr(config_module, "save_config", lambda c: saved.append(c))

    cfg = load_config()

    expected_default = tmp_path / "Apps" / "2.0"
    assert cfg.mtgo.log_dir == expected_default
    assert "default" not in str(cfg.mtgo.log_dir).lower()
    assert len(saved) == 1


def test_config_migration_idempotent_on_migrated_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loading a config whose log_dir has already been migrated is a no-op (no save)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app_dir = tmp_path / "DeepAnalysis"
    app_dir.mkdir(parents=True)
    # Use a POSIX path (matches the default on this CI platform) in a literal TOML string.
    already_ok = str(tmp_path / "Apps" / "2.0")
    (app_dir / "config.toml").write_text(
        f"[mtgo]\nlog_dir = '{already_ok}'\n",
        encoding="utf-8",
    )

    saved: list[AppConfig] = []
    monkeypatch.setattr(config_module, "save_config", lambda c: saved.append(c))

    cfg = load_config()
    assert cfg.mtgo.log_dir == tmp_path / "Apps" / "2.0"
    assert saved == []


def test_config_migration_case_insensitive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lowercase 'users\\default\\' is also detected and rewritten."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app_dir = tmp_path / "DeepAnalysis"
    app_dir.mkdir(parents=True)
    (app_dir / "config.toml").write_text(
        "[mtgo]\nlog_dir = 'c:\\users\\default\\AppData\\Local\\Apps\\2.0\\MTGO'\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module, "save_config", lambda c: None)

    cfg = load_config()
    assert "default" not in str(cfg.mtgo.log_dir).lower()
