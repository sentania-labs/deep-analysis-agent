"""Tests for the in-app SettingsWindow and TrayIcon.reload_config()."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from deep_analysis_agent import settings_window as settings_window_mod
from deep_analysis_agent import tray as tray_mod
from deep_analysis_agent.config import AppConfig
from deep_analysis_agent.settings_window import (
    SettingsWindow,
    apply_autostart_change,
    build_config,
    normalize_server_url,
    validate_form,
)


def test_normalize_server_url_strips_whitespace() -> None:
    assert normalize_server_url("  https://example.com  ") == "https://example.com"


def test_normalize_server_url_prepends_https_when_missing_scheme() -> None:
    assert normalize_server_url("example.com") == "https://example.com"


def test_normalize_server_url_keeps_explicit_http() -> None:
    assert normalize_server_url("http://localhost:8000") == "http://localhost:8000"


def test_normalize_server_url_empty_returns_empty() -> None:
    assert normalize_server_url("   ") == ""


def test_validate_form_accepts_valid_input() -> None:
    assert validate_form(url="https://example.com", heartbeat_interval=60) is None


def test_validate_form_rejects_empty_url() -> None:
    err = validate_form(url="", heartbeat_interval=60)
    assert err is not None
    assert "url" in err.lower()


def test_validate_form_rejects_zero_heartbeat() -> None:
    err = validate_form(url="https://example.com", heartbeat_interval=0)
    assert err is not None
    assert "heartbeat" in err.lower()


def test_validate_form_rejects_negative_heartbeat() -> None:
    err = validate_form(url="https://example.com", heartbeat_interval=-30)
    assert err is not None


def test_build_config_updates_editable_fields() -> None:
    original = AppConfig()
    original.agent.agent_id = "ag-1"
    original.agent.api_token = "tok-secret"
    original.agent.registered_at = datetime(2026, 1, 1, 12, 0, 0)
    original.mtgo.watched_suffixes = [".dat", ".log"]
    original.mtgo.stability_seconds = 7.5

    new = build_config(
        original,
        server_url="https://new.example",
        tls_verify=False,
        machine_name="bench-7",
        heartbeat_interval=120,
        log_dir="/tmp/mtgo-logs",
        log_level="DEBUG",
        log_format="json",
        log_stderr=False,
    )

    assert new.server.url == "https://new.example"
    assert new.server.tls_verify is False
    assert new.agent.machine_name == "bench-7"
    assert new.agent.heartbeat_interval_seconds == 120
    assert new.mtgo.log_dir == Path("/tmp/mtgo-logs")
    assert new.logging.level == "DEBUG"
    assert new.logging.format == "json"
    assert new.logging.stderr is False


def test_build_config_carries_forward_secrets_and_unedited_fields() -> None:
    original = AppConfig()
    original.agent.agent_id = "ag-keep"
    original.agent.api_token = "tok-keep"
    original.agent.registered_at = datetime(2026, 1, 1, 12, 0, 0)
    original.mtgo.watched_suffixes = [".dat", ".log", ".csv"]
    original.mtgo.stability_seconds = 750.0
    original.logging.log_dir = Path("/var/log/da-custom")

    new = build_config(
        original,
        server_url="https://new.example",
        tls_verify=True,
        machine_name="bench-1",
        heartbeat_interval=60,
        log_dir="/tmp/mtgo",
        log_level="INFO",
        log_format="plaintext",
        log_stderr=True,
    )

    assert new.agent.agent_id == "ag-keep"
    assert new.agent.api_token == "tok-keep"
    assert new.agent.registered_at == datetime(2026, 1, 1, 12, 0, 0)
    assert new.mtgo.watched_suffixes == [".dat", ".log", ".csv"]
    assert new.mtgo.stability_seconds == 750.0
    assert new.logging.log_dir == Path("/var/log/da-custom")


def test_settings_window_constructs_without_starting_thread() -> None:
    config = AppConfig()
    saved: list[str] = []
    closed: list[str] = []

    win = SettingsWindow(
        config,
        on_save=lambda: saved.append("yes"),
        on_close=lambda: closed.append("yes"),
    )
    assert win._thread is None
    assert win._root is None


def test_settings_window_close_is_noop_when_root_unset() -> None:
    win = SettingsWindow(AppConfig(), on_save=lambda: None, on_close=lambda: None)
    win.close()


def test_tray_reload_config_loads_and_updates_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    original = AppConfig()
    original.server.url = "https://old.example"
    original.agent.machine_name = "old-machine"

    fresh = AppConfig()
    fresh.server.url = "https://new.example"
    fresh.agent.machine_name = "new-machine"

    monkeypatch.setattr(tray_mod, "load_config", lambda: fresh)
    monkeypatch.setattr(tray_mod, "configure_logging", lambda cfg: None)

    reload_calls: list[AppConfig] = []
    icon = tray_mod.TrayIcon(
        config=original,
        version="0.0.0-test",
        on_reload=lambda cfg: reload_calls.append(cfg),
    )

    icon.reload_config()

    assert icon._config.server.url == "https://new.example"
    assert icon._config.agent.machine_name == "new-machine"
    assert icon._config is original  # same object — mutated in place
    assert len(reload_calls) == 1
    assert reload_calls[0].server.url == "https://new.example"


def test_tray_reload_config_calls_configure_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh = AppConfig()
    fresh.logging.level = "DEBUG"

    monkeypatch.setattr(tray_mod, "load_config", lambda: fresh)
    seen: list[Any] = []
    monkeypatch.setattr(tray_mod, "configure_logging", lambda cfg: seen.append(cfg))

    icon = tray_mod.TrayIcon(config=AppConfig(), version="0.0.0-test")
    icon.reload_config()

    assert len(seen) == 1
    assert seen[0].logging.level == "DEBUG"


def test_tray_reload_config_handles_load_failure_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> AppConfig:
        raise OSError("disk go bye")

    monkeypatch.setattr(tray_mod, "load_config", boom)

    on_reload = MagicMock()
    icon = tray_mod.TrayIcon(
        config=AppConfig(),
        version="0.0.0-test",
        on_reload=on_reload,
    )
    icon.reload_config()  # must not raise

    on_reload.assert_not_called()


def test_settings_window_save_callback_signature() -> None:
    """SettingsWindow should accept a no-arg ``on_save`` callable (e.g. tray.reload_config)."""
    config = AppConfig()
    win = SettingsWindow(config, on_save=lambda: None, on_close=lambda: None)
    assert win._on_save is not None


def _patch_autostart(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
    enable_result: bool = True,
    disable_result: bool = True,
) -> dict[str, int]:
    """Patch the autostart facade used by settings_window. Returns a call counter."""
    calls = {"enable": 0, "disable": 0, "is_enabled": 0}

    def _is_enabled() -> bool:
        calls["is_enabled"] += 1
        return enabled

    def _enable() -> bool:
        calls["enable"] += 1
        return enable_result

    def _disable() -> bool:
        calls["disable"] += 1
        return disable_result

    monkeypatch.setattr(settings_window_mod.autostart, "is_enabled", _is_enabled)
    monkeypatch.setattr(settings_window_mod.autostart, "enable", _enable)
    monkeypatch.setattr(settings_window_mod.autostart, "disable", _disable)
    return calls


def test_apply_autostart_change_noop_when_already_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the registry already reflects the desired state, no enable/disable call."""
    calls = _patch_autostart(monkeypatch, enabled=True)
    assert apply_autostart_change(desired=True) is None
    assert calls["enable"] == 0
    assert calls["disable"] == 0


def test_apply_autostart_change_noop_when_already_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_autostart(monkeypatch, enabled=False)
    assert apply_autostart_change(desired=False) is None
    assert calls["enable"] == 0
    assert calls["disable"] == 0


def test_apply_autostart_change_enables_when_flipped_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_autostart(monkeypatch, enabled=False)
    assert apply_autostart_change(desired=True) is None
    assert calls["enable"] == 1
    assert calls["disable"] == 0


def test_apply_autostart_change_disables_when_flipped_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_autostart(monkeypatch, enabled=True)
    assert apply_autostart_change(desired=False) is None
    assert calls["enable"] == 0
    assert calls["disable"] == 1


def test_apply_autostart_change_returns_message_on_enable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When enable() returns False, the helper surfaces a user-facing warning string."""
    _patch_autostart(monkeypatch, enabled=False, enable_result=False)
    err = apply_autostart_change(desired=True)
    assert err is not None
    assert "enable" in err.lower()


def test_apply_autostart_change_returns_message_on_disable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_autostart(monkeypatch, enabled=True, disable_result=False)
    err = apply_autostart_change(desired=False)
    assert err is not None
    assert "disable" in err.lower()
