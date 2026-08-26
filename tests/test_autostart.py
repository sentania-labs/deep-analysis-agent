"""Tests for the Windows-login autostart toggle.

The real implementation calls ``winreg`` (Windows-only stdlib). These
tests run on Linux CI, so we stub the registry with an in-memory dict
and route ``autostart._is_windows`` to True so the production code path
exercises.
"""

from __future__ import annotations

import sys
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

    sys.modules["winreg"].OpenKey = _explode  # type: ignore[attr-defined]
    assert autostart.enable() is False


# --- Squirrel stable entry point (issue #42) ------------------------------
#
# On a Squirrel install the running exe lives in a versioned ``app-*``
# directory that is replaced on update, so the Run key must go through
# ``Update.exe`` instead. These tests fake the on-disk layout under
# ``tmp_path`` and the ``sys.frozen`` / ``sys.executable`` pair; no real
# Windows install is involved.


@pytest.fixture
def squirrel_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Build a fake Squirrel layout and point ``sys.executable`` into it.

    Returns ``(update_exe, app_exe)``.
    """
    root = tmp_path / "DeepAnalysisAgent"
    app_dir = root / "app-0.4.8"
    app_dir.mkdir(parents=True)
    update_exe = root / "Update.exe"
    update_exe.write_text("stub", encoding="utf-8")
    app_exe = app_dir / "DeepAnalysisAgent.exe"
    app_exe.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_exe))
    return update_exe.resolve(), app_exe


@pytest.fixture
def frozen_non_squirrel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A frozen exe with no ``Update.exe`` above it (PyInstaller-only build)."""
    exe = tmp_path / "standalone" / "DeepAnalysisAgent.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    return exe


def test_exe_command_dev_uses_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-frozen dev run: the Run command is just the quoted executable."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    cmd = autostart._exe_command()
    assert cmd == f'"{sys.executable}"'
    assert "--processStart" not in cmd


def test_exe_command_frozen_non_squirrel_uses_exe(frozen_non_squirrel: Path) -> None:
    """Frozen but no Update.exe alongside: fall back to the exe path."""
    cmd = autostart._exe_command()
    assert cmd == f'"{frozen_non_squirrel}"'
    assert "--processStart" not in cmd


def test_exe_command_squirrel_uses_update_exe(squirrel_install: tuple[Path, Path]) -> None:
    """Squirrel layout: go through the stable Update.exe entry point."""
    update_exe, app_exe = squirrel_install
    cmd = autostart._exe_command()
    assert cmd == f'"{update_exe}" --processStart DeepAnalysisAgent.exe'
    # The versioned app dir must not appear anywhere in the command.
    assert "app-0.4.8" not in cmd
    assert str(app_exe) not in cmd


def test_enable_writes_squirrel_command(
    fake_registry: _FakeWinreg, squirrel_install: tuple[Path, Path]
) -> None:
    update_exe, _ = squirrel_install
    assert autostart.enable() is True
    assert (
        fake_registry.store["DeepAnalysisAgent"]
        == f'"{update_exe}" --processStart DeepAnalysisAgent.exe'
    )


@pytest.mark.parametrize(
    ("value", "stale"),
    [
        (r'"C:\Users\s\AppData\Local\DeepAnalysisAgent\app-0.4.8\DeepAnalysisAgent.exe"', True),
        (
            r'"C:\Users\s\AppData\Local\DeepAnalysisAgent\app-1.2.3-beta\DeepAnalysisAgent.exe"',
            True,
        ),
        (
            r'"C:\Users\s\AppData\Local\DeepAnalysisAgent\Update.exe" '
            r"--processStart DeepAnalysisAgent.exe",
            False,
        ),
        (r'"C:\Program Files\Python312\python.exe" -m deep_analysis_agent', False),
        (r'"C:\tools\DeepAnalysisAgent\DeepAnalysisAgent.exe"', False),
        # Windows paths are case-insensitive: App-0.4.8 is the same dir.
        (r'"C:\Users\s\AppData\Local\DeepAnalysisAgent\App-0.4.8\DeepAnalysisAgent.exe"', True),
        # Forward slashes are legal in Win32 API paths.
        ('"C:/Users/s/AppData/Local/DeepAnalysisAgent/app-0.4.8/DeepAnalysisAgent.exe"', True),
        # Unquoted, with trailing arguments.
        (
            r"C:\Users\s\AppData\Local\DeepAnalysisAgent\app-0.4.8\DeepAnalysisAgent.exe --quiet",
            True,
        ),
        # An Update.exe command is never stale, wherever it lives.
        (r'"C:\Users\s\Update.exe" --processStart DeepAnalysisAgent.exe', False),
    ],
)
def test_is_stale_command(value: str, stale: bool) -> None:
    assert autostart._is_stale_command(value) is stale


def test_migrate_rewrites_stale_value(
    fake_registry: _FakeWinreg, squirrel_install: tuple[Path, Path]
) -> None:
    """A Run key left by an older build is repointed at Update.exe."""
    update_exe, app_exe = squirrel_install
    fake_registry.store["DeepAnalysisAgent"] = f'"{app_exe}"'
    assert autostart.migrate_stale_command() is True
    assert (
        fake_registry.store["DeepAnalysisAgent"]
        == f'"{update_exe}" --processStart DeepAnalysisAgent.exe'
    )


def test_migrate_is_noop_when_already_stable(
    fake_registry: _FakeWinreg, squirrel_install: tuple[Path, Path]
) -> None:
    update_exe, _ = squirrel_install
    stable = f'"{update_exe}" --processStart DeepAnalysisAgent.exe'
    fake_registry.store["DeepAnalysisAgent"] = stable
    assert autostart.migrate_stale_command() is False
    assert fake_registry.store["DeepAnalysisAgent"] == stable


def test_migrate_does_not_reenable_after_opt_out(
    fake_registry: _FakeWinreg, squirrel_install: tuple[Path, Path]
) -> None:
    """No Run value means the user opted out: migration must not write one."""
    assert autostart.is_enabled() is False
    assert autostart.migrate_stale_command() is False
    assert "DeepAnalysisAgent" not in fake_registry.store


def test_migrate_is_noop_on_dev_build(
    fake_registry: _FakeWinreg, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a Squirrel layout there is no better command to write."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    stale = r'"C:\Users\s\AppData\Local\DeepAnalysisAgent\app-0.4.8\DeepAnalysisAgent.exe"'
    fake_registry.store["DeepAnalysisAgent"] = stale
    assert autostart.migrate_stale_command() is False
    assert fake_registry.store["DeepAnalysisAgent"] == stale


def test_migrate_is_noop_off_windows(
    monkeypatch: pytest.MonkeyPatch, squirrel_install: tuple[Path, Path]
) -> None:
    monkeypatch.setattr(autostart, "_is_windows", lambda: False)
    assert autostart.migrate_stale_command() is False


def test_migrate_reports_failure_when_registry_write_fails(
    fake_registry: _FakeWinreg,
    squirrel_install: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed write leaves the stale value alone and reports False, so the
    next launch tries again rather than silently claiming success."""
    _, app_exe = squirrel_install
    stale = f'"{app_exe}"'
    fake_registry.store["DeepAnalysisAgent"] = stale
    monkeypatch.setattr(autostart, "enable", lambda: False)
    assert autostart.migrate_stale_command() is False
    assert fake_registry.store["DeepAnalysisAgent"] == stale


def test_exe_command_quotes_exe_name_with_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The --processStart argument is quoted if the exe name has a space."""
    root = tmp_path / "DeepAnalysisAgent"
    app_dir = root / "app-0.4.8"
    app_dir.mkdir(parents=True)
    (root / "Update.exe").write_text("stub", encoding="utf-8")
    exe = app_dir / "Deep Analysis Agent.exe"
    exe.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    cmd = autostart._exe_command()
    assert cmd.endswith('--processStart "Deep Analysis Agent.exe"')
