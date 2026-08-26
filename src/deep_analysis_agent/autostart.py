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
import re
import sys
from pathlib import Path
from typing import Any

from .paths import SQUIRREL_APP_DIR_PREFIX, app_data_dir, squirrel_update_exe

logger = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "DeepAnalysisAgent"
_INIT_MARKER = ".autostart_initialized"

#: Matches a path segment like ``\app-0.4.8\`` written by older builds that
#: registered the versioned Squirrel binary directly. Windows paths are
#: case-insensitive, so ``App-0.4.8`` names the same directory and must
#: migrate too.
_VERSIONED_DIR_RE = re.compile(
    r"[\\/]" + re.escape(SQUIRREL_APP_DIR_PREFIX) + r"[^\\/]*[\\/]",
    re.IGNORECASE,
)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _exe_command() -> str:
    """Return the command Windows should run on login, quoted for spaces.

    On a Squirrel install this is the stable entry point
    ``Update.exe --processStart DeepAnalysisAgent.exe`` rather than the
    running exe's own path. The running exe lives in a versioned
    ``app-<version>`` directory that Squirrel replaces on update, so a Run
    key pointing at it keeps launching the old build after an update
    (issue #42). ``Update.exe`` sits outside the versioned dirs and always
    starts the newest installed version.

    Dev runs and frozen non-Squirrel builds fall back to the exe path.
    """
    update_exe = squirrel_update_exe()
    if update_exe is not None:
        name = Path(sys.executable).name
        if any(c.isspace() for c in name):
            name = f'"{name}"'
        return f'"{update_exe}" --processStart {name}'
    return f'"{sys.executable}"'


def _is_stale_command(cmd: str) -> bool:
    """True if ``cmd`` launches a versioned Squirrel binary directly.

    A command that already goes through ``--processStart`` is fine no
    matter what else it mentions; anything else naming an ``app-*``
    directory segment is the pre-fix form.
    """
    if "--processstart" in cmd.lower():
        return False
    return _VERSIONED_DIR_RE.search(cmd) is not None


def _winreg() -> Any:
    """Return the Windows ``winreg`` module. Caller guards on ``_is_windows``."""
    import winreg

    return winreg


def _current_command() -> str | None:
    """Return the Run-key value for this agent, or None if absent/unreadable."""
    if not _is_windows():
        return None
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _type = winreg.QueryValueEx(key, _VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return None
    except OSError:
        logger.exception("autostart_read_failed")
        return None


def is_enabled() -> bool:
    """True iff the Run-key value for this agent is present."""
    return _current_command() is not None


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
    if default_enabled and not enable():
        # Leave the marker absent so the next launch retries enable()
        # rather than permanently locking in a transient registry error.
        logger.warning("autostart_enable_failed_will_retry_next_launch")
        return
    try:
        marker.write_text("1", encoding="utf-8")
    except OSError:
        logger.exception("autostart_marker_write_failed")


def migrate_stale_command() -> bool:
    """Rewrite a Run-key value that points straight at a versioned binary.

    Users who installed before this fix already have
    ``...\\app-0.4.8\\DeepAnalysisAgent.exe`` in their Run key, which no
    amount of updating will correct on its own. Called on startup: if the
    stored value is the stale form and we can build the Squirrel command,
    replace it. Returns True only when a rewrite actually happened.

    Deliberately does nothing when autostart is off (no value present) so
    a user opt-out is never undone, and nothing on dev/non-Squirrel
    builds where there is no better command to write.
    """
    if not _is_windows():
        return False
    if squirrel_update_exe() is None:
        return False
    current = _current_command()
    if current is None or not _is_stale_command(current):
        return False
    desired = _exe_command()
    logger.info("autostart_migrating_stale_command old=%s new=%s", current, desired)
    return enable()


def toggle() -> bool:
    """Flip current state. Returns the new state (True == enabled)."""
    if is_enabled():
        disable()
        return False
    enable()
    return True
