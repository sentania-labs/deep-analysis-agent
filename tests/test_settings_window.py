"""Tests for the in-app SettingsWindow and TrayIcon.reload_config()."""

from __future__ import annotations

import os
import sys
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
    parse_lines,
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


def test_parse_lines_trims_and_drops_empty_lines() -> None:
    assert parse_lines("  .dat\n\n *.xml \n") == [".dat", "*.xml"]


def test_validate_form_rejects_empty_watched_name_globs() -> None:
    err = validate_form(
        url="https://example.com",
        heartbeat_interval=60,
        watched_name_globs=[],
    )
    assert err == "At least one watched name glob is required."


def test_validate_form_rejects_enabled_card_data_without_directory() -> None:
    err = validate_form(
        url="https://example.com",
        heartbeat_interval=60,
        card_data_source_enabled=True,
        card_data_source_dir="  ",
    )
    assert err == "Choose a CardDataSource directory or disable card data uploads."


def test_validate_form_accepts_disabled_card_data_without_directory() -> None:
    assert (
        validate_form(
            url="https://example.com",
            heartbeat_interval=60,
            card_data_source_enabled=False,
            card_data_source_dir="",
        )
        is None
    )


def test_validate_form_accepts_enabled_card_data_with_auto_detect() -> None:
    assert (
        validate_form(
            url="https://example.com",
            heartbeat_interval=60,
            card_data_source_enabled=True,
            card_data_source_auto_detect=True,
            card_data_source_dir="",
        )
        is None
    )


def _form_values(original: AppConfig) -> dict[str, Any]:
    """Return form values that preserve every operator-editable setting."""
    raw_tls = original.server.tls_verify
    return {
        "server_url": original.server.url,
        "tls_verify": bool(raw_tls),
        "tls_ca_bundle": raw_tls if isinstance(raw_tls, str) else "",
        "machine_name": original.agent.machine_name,
        "heartbeat_interval": original.agent.heartbeat_interval_seconds,
        "log_dir": str(original.mtgo.log_dir),
        "watched_suffixes": original.mtgo.watched_suffixes,
        "watched_name_globs": original.mtgo.watched_name_globs,
        "stability_seconds": original.mtgo.stability_seconds,
        "card_data_source_enabled": original.mtgo.card_data_source_enabled,
        "card_data_source_auto_detect": original.mtgo.card_data_source_dir is None,
        "card_data_source_dir": (
            str(original.mtgo.card_data_source_dir) if original.mtgo.card_data_source_dir else ""
        ),
        "log_level": original.logging.level,
        "logging_dir": str(original.logging.log_dir) if original.logging.log_dir else "",
        "log_format": original.logging.format,
        "log_stderr": original.logging.stderr,
    }


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
        tls_ca_bundle="",
        machine_name="bench-7",
        heartbeat_interval=120,
        log_dir="/tmp/mtgo-logs",
        watched_suffixes=[".dat", ".xml"],
        watched_name_globs=["Match_GameLog_*.dat", "grouping *.xml"],
        stability_seconds=1200.0,
        card_data_source_enabled=True,
        card_data_source_auto_detect=False,
        card_data_source_dir="/tmp/cards",
        log_level="DEBUG",
        logging_dir="/tmp/logs",
        log_format="json",
        log_stderr=False,
    )

    assert new.server.url == "https://new.example"
    assert new.server.tls_verify is False
    assert new.agent.machine_name == "bench-7"
    assert new.agent.heartbeat_interval_seconds == 120
    assert new.mtgo.log_dir == Path("/tmp/mtgo-logs")
    assert new.mtgo.watched_suffixes == [".dat", ".xml"]
    assert new.mtgo.watched_name_globs == ["Match_GameLog_*.dat", "grouping *.xml"]
    assert new.mtgo.stability_seconds == 1200.0
    assert new.mtgo.card_data_source_enabled is True
    assert new.mtgo.card_data_source_dir == Path("/tmp/cards")
    assert new.logging.level == "DEBUG"
    assert new.logging.log_dir == Path("/tmp/logs")
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

    form = _form_values(original)
    form.update(server_url="https://new.example", machine_name="bench-1")
    new = build_config(original, **form)

    assert new.agent.agent_id == "ag-keep"
    assert new.agent.api_token == "tok-keep"
    assert new.agent.registered_at == datetime(2026, 1, 1, 12, 0, 0)
    assert new.mtgo.watched_suffixes == [".dat", ".log", ".csv"]
    assert new.mtgo.stability_seconds == 750.0
    assert new.logging.log_dir == Path("/var/log/da-custom")


def _isolate_config_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point config discovery at an empty tmp dir and drop env overrides.

    Without this, ``AppConfig()`` picks up a real ``config.toml`` and any
    ``DEEP_ANALYSIS_*`` env vars, so the default-vs-real-value comparisons
    below would reflect the machine rather than the schema.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for name in list(os.environ):
        if name.startswith("DEEP_ANALYSIS_"):
            monkeypatch.delenv(name, raising=False)


def _fully_populated_config() -> AppConfig:
    """An AppConfig where every field holds a distinctive non-default value."""
    cfg = AppConfig()

    cfg.server.url = "https://old.example"
    cfg.server.tls_verify = "/etc/ssl/custom-ca.pem"

    cfg.agent.machine_name = "old-bench"
    cfg.agent.agent_id = "ag-full"
    cfg.agent.api_token = "tok-full"
    cfg.agent.registered_at = datetime(2026, 2, 3, 4, 5, 6)
    cfg.agent.heartbeat_interval_seconds = 999

    cfg.mtgo.log_dir = Path("/old/mtgo/logs")
    cfg.mtgo.watched_suffixes = [".dat", ".xml", ".csv"]
    cfg.mtgo.watched_name_globs = ["Match_GameLog_*.dat"]
    cfg.mtgo.stability_seconds = 900.0
    cfg.mtgo.card_data_source_dir = Path("/old/card/data")
    cfg.mtgo.card_data_source_enabled = False

    cfg.logging.level = "ERROR"
    cfg.logging.log_dir = Path("/var/log/da-full")
    cfg.logging.stderr = False
    cfg.logging.format = "json"

    return cfg


def _save_with_unrelated_edit(original: AppConfig) -> AppConfig:
    """Save the settings form changing only the machine name."""
    form = _form_values(original)
    form["machine_name"] = "renamed-bench"
    return build_config(original, **form)


def test_build_config_preserves_advanced_mtgo_values_during_unrelated_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Advanced MTGO fields survive when an operator edits another section."""
    _isolate_config_sources(monkeypatch, tmp_path)
    original = _fully_populated_config()

    new = _save_with_unrelated_edit(original)

    assert new.agent.machine_name == "renamed-bench"
    assert new.mtgo.watched_name_globs == ["Match_GameLog_*.dat"]
    assert new.mtgo.card_data_source_dir == Path("/old/card/data")
    assert new.mtgo.card_data_source_enabled is False


# Dotted paths the settings form is allowed to change. Everything else must
# round-trip through build_config untouched.
EDITABLE_PATHS = frozenset(
    {
        "server.url",
        "server.tls_verify",
        "agent.machine_name",
        "agent.heartbeat_interval_seconds",
        "mtgo.log_dir",
        "mtgo.watched_suffixes",
        "mtgo.watched_name_globs",
        "mtgo.stability_seconds",
        "mtgo.card_data_source_dir",
        "mtgo.card_data_source_enabled",
        "logging.level",
        "logging.log_dir",
        "logging.stderr",
        "logging.format",
    }
)

INTERNAL_PATHS = frozenset(
    {
        "agent.agent_id",
        "agent.api_token",
        "agent.registered_at",
    }
)


def test_settings_audit_classifies_every_persisted_model_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every persisted field is explicitly editable or runtime-managed."""
    _isolate_config_sources(monkeypatch, tmp_path)
    paths = {
        f"{section}.{field}"
        for section, fields in AppConfig().model_dump().items()
        for field in fields
    }

    assert EDITABLE_PATHS.isdisjoint(INTERNAL_PATHS)
    assert paths == EDITABLE_PATHS | INTERNAL_PATHS


def test_build_config_preserves_custom_ca_bundle() -> None:
    original = AppConfig()
    original.server.tls_verify = "C:/certs/lab-ca.pem"

    new = build_config(original, **_form_values(original))

    assert new.server.tls_verify == "C:/certs/lab-ca.pem"


def test_build_config_preserves_card_data_auto_detection() -> None:
    original = AppConfig()
    assert original.mtgo.card_data_source_enabled is True
    assert original.mtgo.card_data_source_dir is None

    new = build_config(original, **_form_values(original))

    assert new.mtgo.card_data_source_enabled is True
    assert new.mtgo.card_data_source_dir is None


def test_build_config_preserves_every_unedited_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard: any field build_config drops shows up here, named.

    This walks the whole model rather than a hand-written field list, so a
    field added to MTGOSettings (or any other section) later is covered
    automatically instead of silently resetting on save.
    """
    _isolate_config_sources(monkeypatch, tmp_path)
    original = _fully_populated_config()

    new = _save_with_unrelated_edit(original)

    before = original.model_dump()
    after = new.model_dump()
    dropped = {
        f"{section}.{field}": (value, after[section][field])
        for section, fields in before.items()
        for field, value in fields.items()
        if f"{section}.{field}" not in EDITABLE_PATHS and after[section][field] != value
    }
    assert dropped == {}


def test_build_config_guard_covers_all_config_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard: a new config field must be populated in _fully_populated_config.

    Without this, adding a field would leave the preservation test comparing
    default against default and passing vacuously.
    """
    _isolate_config_sources(monkeypatch, tmp_path)
    populated = _fully_populated_config()
    defaults = AppConfig()

    unpopulated = [
        f"{section}.{field}"
        for section, fields in populated.model_dump().items()
        for field, value in fields.items()
        if defaults.model_dump()[section][field] == value
    ]
    assert unpopulated == []


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


@pytest.mark.parametrize(
    "change",
    ["enable", "disable", "directory", "auto_detect", "unrelated", "log_error", "ca_error"],
)
def test_save_card_data_restart_notice(
    monkeypatch: pytest.MonkeyPatch, change: str, tmp_path: Path
) -> None:
    tk = MagicMock()
    tk.TclError = RuntimeError
    variables: list[MagicMock] = []

    def variable(*, value: Any) -> MagicMock:
        var = MagicMock()
        var.get.return_value = value
        var.set.side_effect = lambda value: setattr(var.get, "return_value", value)
        variables.append(var)
        return var

    def text_widget(*args: Any, **kwargs: Any) -> MagicMock:
        widget = MagicMock()
        widget.insert.side_effect = lambda index, text: setattr(widget.get, "return_value", text)
        return widget

    tk.StringVar.side_effect = variable
    tk.BooleanVar.side_effect = variable
    tk.IntVar.side_effect = variable
    tk.Text.side_effect = text_widget
    root = tk.Tk.return_value
    root.winfo_screenheight.return_value = 1000
    tk.ttk.Frame.return_value.winfo_reqheight.return_value = 1200
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setattr(settings_window_mod.autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(settings_window_mod, "apply_autostart_change", lambda enabled: None)
    save = MagicMock()
    monkeypatch.setattr(settings_window_mod, "save_config", save)
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.logging.log_dir = tmp_path / "logs"
    if change == "ca_error":
        cfg.server.tls_verify = str(tmp_path / "original.pem")
    cfg.mtgo.card_data_source_enabled = change != "enable"
    cfg.mtgo.card_data_source_dir = Path("old-cards")
    original = cfg.model_dump()
    reload_callback = MagicMock()
    notices: list[str] = []

    def interact() -> None:
        if change == "log_error":
            invalid_dir = tmp_path / "blocked"
            invalid_dir.write_text("This is a file, not a directory.")
            next(var for var in variables if var.get() == str(tmp_path / "logs")).set(
                str(invalid_dir)
            )
        if change == "ca_error":
            invalid_bundle = tmp_path / "invalid.der"
            invalid_bundle.write_bytes(b"\x30\x82invalid certificate")
            next(var for var in variables if var.get() == cfg.server.tls_verify).set(
                str(invalid_bundle)
            )
        for call in tk.ttk.Checkbutton.call_args_list:
            if (
                call.kwargs.get("text") == "Upload MTGO card data"
                and change in {"enable", "disable"}
            ):
                call.kwargs["variable"].set(change == "enable")
            if (
                call.kwargs.get("text") == "Auto-detect from MTGO log directory"
                and change == "auto_detect"
            ):
                call.kwargs["variable"].set(True)
        if change == "directory":
            next(var for var in variables if var.get() == "old-cards").set("new-cards")
        if change == "unrelated":
            next(var for var in variables if var.get() == "https://example.test").set(
                "https://other.test"
            )
        save_button = next(
            call.kwargs["command"]
            for call in tk.ttk.Button.call_args_list
            if call.kwargs.get("text") == "Save"
        )
        save_button()
        notices.extend(str(var.get()) for var in variables)

    root.mainloop.side_effect = interact
    SettingsWindow(cfg, on_save=reload_callback)._run()

    if change in {"log_error", "ca_error"}:
        save.assert_not_called()
        reload_callback.assert_not_called()
        root.destroy.assert_not_called()
        assert cfg.model_dump() == original
        error = "Cannot load CA bundle:" if change == "ca_error" else "Cannot open agent.log"
        assert any(notice.startswith(error) for notice in notices)
        assert not any(notice.startswith("Settings saved.") for notice in notices)
        return
    save.assert_called_once()
    reload_callback.assert_called_once_with()
    tk.messagebox.showerror.assert_not_called()
    notice = "Settings saved. CardDataSource changes apply after the agent restarts."
    if change == "unrelated":
        assert notice not in notices
        root.destroy.assert_called_once()
    else:
        assert notice in notices
        root.destroy.assert_not_called()
        tk.Canvas.return_value.yview_moveto.assert_called_once_with(1.0)
        tk.ttk.Button.return_value.configure.assert_called_with(text="Close")
    saved = save.call_args.args[0]
    if change in {"enable", "disable"}:
        assert saved.mtgo.card_data_source_enabled is (change == "enable")
    elif change == "directory":
        assert saved.mtgo.card_data_source_dir == Path("new-cards")
    elif change == "auto_detect":
        assert saved.mtgo.card_data_source_dir is None


@pytest.mark.parametrize("existing_log", [False, True])
def test_validate_destinations_accepts_pem_and_writable_log(
    tmp_path: Path, existing_log: bool
) -> None:
    import certifi

    cfg = AppConfig()
    cfg.server.tls_verify = certifi.where()
    cfg.logging.log_dir = tmp_path / "logs"
    target = cfg.logging.log_dir / "agent.log"
    if existing_log:
        target.parent.mkdir()
        target.write_text("existing log data", encoding="utf-8")
    assert settings_window_mod.validate_destinations(cfg) is None
    assert target.read_text(encoding="utf-8") == ("existing log data" if existing_log else "")


def test_validate_destinations_rejects_unwritable_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = AppConfig()
    cfg.logging.log_dir = tmp_path
    open_log = MagicMock(side_effect=PermissionError("Access denied"))
    monkeypatch.setattr(Path, "open", open_log)
    error = settings_window_mod.validate_destinations(cfg)
    assert error is not None
    assert error.startswith("Cannot open agent.log")
    open_log.assert_called_once_with("a", encoding="utf-8")
