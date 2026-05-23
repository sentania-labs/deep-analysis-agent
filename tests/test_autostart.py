"""Tests for the Windows-login autostart toggle.

The real implementation calls ``winreg`` (Windows-only stdlib). These
tests run on Linux CI, so we stub the registry with an in-memory dict
and route ``autostart._is_windows`` to True so the production code path
exercises.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from deep_analysis_agent import autostart


class _FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_READ = 0
    KEY_SET_VALUE = 0
    REG_SZ = 1

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    class _Key:
        def __init__(self, registry: _FakeWinreg) -> None:
            self._registry = registry

        def __enter__(self) -> _FakeWinreg._Key:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def OpenKey(self, _root: object, _path: str, _reserved: int, _access: int) -> _FakeWinreg._Key:
        return _FakeWinreg._Key(self)

    def QueryValueEx(self, _key: _FakeWinreg._Key, name: str) -> tuple[str, int]:
        if name not in self.store:
            raise FileNotFoundError(name)
        return self.store[name], self.REG_SZ

    def SetValueEx(
        self,
        _key: _FakeWinreg._Key,
        name: str,
        _reserved: int,
        _type: int,
        value: str,
    ) -> None:
        self.store[name] = value

    def DeleteValue(self, _key: _FakeWinreg._Key, name: str) -> None:
        if name not in self.store:
            raise FileNotFoundError(name)
        del self.store[name]


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeWinreg]:
    fake = _FakeWinreg()
    fake_module = ModuleType("winreg")
    for attr in (
        "HKEY_CURRENT_USER",
        "KEY_READ",
        "KEY_SET_VALUE",
        "REG_SZ",
        "OpenKey",
        "QueryValueEx",
        "SetValueEx",
        "DeleteValue",
    ):
        setattr(fake_module, attr, getattr(fake, attr))

    import sys

    monkeypatch.setitem(sys.modules, "winreg", fake_module)
    monkeypatch.setattr(autostart, "_is_windows", lambda: True)
    yield fake


def test_enable_writes_run_key(fake_registry: _FakeWinreg) -> None:
    assert autostart.enable() is True
    assert "DeepAnalysisAgent" in fake_registry.store
    assert fake_registry.store["DeepAnalysisAgent"].startswith('"')


def test_is_enabled_reflects_state(fake_registry: _FakeWinreg) -> None:
    assert autostart.is_enabled() is False
    autostart.enable()
    assert autostart.is_enabled() is True


def test_disable_removes_run_key(fake_registry: _FakeWinreg) -> None:
    autostart.enable()
    assert autostart.is_enabled() is True
    assert autostart.disable() is True
    assert autostart.is_enabled() is False


def test_disable_when_absent_is_idempotent(fake_registry: _FakeWinreg) -> None:
    assert autostart.is_enabled() is False
    assert autostart.disable() is True


def test_toggle_flips_state(fake_registry: _FakeWinreg) -> None:
    assert autostart.is_enabled() is False
    assert autostart.toggle() is True
    assert autostart.is_enabled() is True
    assert autostart.toggle() is False
    assert autostart.is_enabled() is False


def test_ensure_default_enables_on_first_run(
    fake_registry: _FakeWinreg,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(autostart, "app_data_dir", lambda: tmp_path)
    assert autostart.is_enabled() is False
    autostart.ensure_default(default_enabled=True)
    assert autostart.is_enabled() is True
    assert (tmp_path / autostart._INIT_MARKER).exists()


def test_ensure_default_respects_opt_out(
    fake_registry: _FakeWinreg,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the user disables autostart, we don't re-enable it on next launch."""
    monkeypatch.setattr(autostart, "app_data_dir", lambda: tmp_path)
    autostart.ensure_default(default_enabled=True)
    assert autostart.is_enabled() is True
    # User opts out.
    autostart.disable()
    assert autostart.is_enabled() is False
    # Next launch: ensure_default must not re-enable.
    autostart.ensure_default(default_enabled=True)
    assert autostart.is_enabled() is False


def test_ensure_default_disabled_path(
    fake_registry: _FakeWinreg,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """default_enabled=False writes the marker without enabling autostart."""
    monkeypatch.setattr(autostart, "app_data_dir", lambda: tmp_path)
    autostart.ensure_default(default_enabled=False)
    assert autostart.is_enabled() is False
    assert (tmp_path / autostart._INIT_MARKER).exists()


def test_ensure_default_skips_marker_on_enable_failure(
    fake_registry: _FakeWinreg,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If enable() fails (e.g. transient registry error), the init marker
    must not be written so the next launch retries — rather than
    permanently locking in the failure with autostart never registered."""
    monkeypatch.setattr(autostart, "app_data_dir", lambda: tmp_path)

    enable_calls = {"n": 0}

    def _fail_enable() -> bool:
        enable_calls["n"] += 1
        return False

    monkeypatch.setattr(autostart, "enable", _fail_enable)
    autostart.ensure_default(default_enabled=True)
    assert not (tmp_path / autostart._INIT_MARKER).exists()
    assert enable_calls["n"] == 1
    # Next launch must retry enable() (marker absent).
    autostart.ensure_default(default_enabled=True)
    assert enable_calls["n"] == 2
    assert not (tmp_path / autostart._INIT_MARKER).exists()


def test_noop_off_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """On non-Windows, all functions short-circuit cleanly."""
    monkeypatch.setattr(autostart, "_is_windows", lambda: False)
    monkeypatch.setattr(autostart, "app_data_dir", lambda: tmp_path)
    assert autostart.is_enabled() is False
    assert autostart.enable() is False
    assert autostart.disable() is False
    autostart.ensure_default()
    assert autostart.is_enabled() is False


def test_enable_handles_winreg_oserror(
    monkeypatch: pytest.MonkeyPatch, fake_registry: _FakeWinreg
) -> None:
    """A non-FileNotFoundError OSError from winreg returns False, not raise."""

    def _explode(*_a: Any, **_kw: Any) -> Any:
        raise OSError("registry handle leak simulation")

    import sys

    sys.modules["winreg"].OpenKey = _explode  # type: ignore[attr-defined]
    assert autostart.enable() is False
