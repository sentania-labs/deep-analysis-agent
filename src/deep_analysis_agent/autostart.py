"""Autostart on Windows login via the per-user Run registry key.

The agent registers itself under
``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`` so Windows
launches the tray service when the user logs in. Per-user means no UAC,
matches the per-user Squirrel install location, and the user can flip
the toggle from the tray menu without elevated privileges.

A one-shot marker file (`.autostart_initialized` in the app data dir)
records that the default has been applied so we never override a user
opt-out on subsequent runs.

Off-Windows: all functions log and return without touching anything.
``winreg`` is in the stdlib on Windows only.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from .paths import app_data_dir

logger = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "DeepAnalysisAgent"
_INIT_MARKER = ".autostart_initialized"


def _is_windows() -> bool:
    return sys.platform == "win32"


def _exe_command() -> str:
    """Return the command Windows should run on login, quoted for spaces."""
    exe = sys.executable
    return f'"{exe}"'


def _winreg() -> Any:
    """Return the Windows ``winreg`` module. Caller guards on ``_is_windows``."""
    import winreg

    return winreg


def is_enabled() -> bool:
    """True iff the Run-key value for this agent is present."""
    if not _is_windows():
        return False
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        logger.exception("autostart_is_enabled_failed")
        return False


def enable() -> bool:
    """Register the agent for login start. Returns True on success."""
    if not _is_windows():
        logger.debug("autostart_enable_noop platform=%s", sys.platform)
        return False
    winreg = _winreg()
    cmd = _exe_command()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, cmd)
        logger.info("autostart_enabled cmd=%s", cmd)
        return True
    except OSError:
        logger.exception("autostart_enable_failed")
        return False


def disable() -> bool:
    """Remove the agent's Run-key value. Idempotent."""
    if not _is_windows():
        logger.debug("autostart_disable_noop platform=%s", sys.platform)
        return False
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
        logger.info("autostart_disabled")
        return True
    except FileNotFoundError:
        return True
    except OSError:
        logger.exception("autostart_disable_failed")
        return False


def _marker_path() -> Path:
    return app_data_dir() / _INIT_MARKER


def ensure_default(default_enabled: bool = True) -> None:
    """Apply the default autostart setting once, then never again.

    Persistence lives entirely in the registry; this marker just records
    that we've applied the *default* so a user who toggles off won't be
    re-enabled on the next launch.
    """
    marker = _marker_path()
    if marker.exists():
        return
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("autostart_marker_dir_failed")
        return
    if default_enabled:
        enable()
    try:
        marker.write_text("1", encoding="utf-8")
    except OSError:
        logger.exception("autostart_marker_write_failed")


def toggle() -> bool:
    """Flip current state. Returns the new state (True == enabled)."""
    if is_enabled():
        disable()
        return False
    enable()
    return True
