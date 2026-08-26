"""Shared path helpers for agent data files (config, logs, dedup DB)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "DeepAnalysis"

#: Squirrel installs the frozen exe into a versioned ``app-<version>`` dir.
SQUIRREL_APP_DIR_PREFIX = "app-"


def app_data_dir() -> Path:
    """Return `%LOCALAPPDATA%\\DeepAnalysis`, or a ~/.local fallback off-Windows."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def config_path() -> Path:
    return app_data_dir() / "config.toml"


def dedup_path() -> Path:
    return app_data_dir() / "dedup.db"


def logs_dir() -> Path:
    return app_data_dir() / "logs"


def squirrel_update_exe() -> Path | None:
    """Return the Squirrel ``Update.exe`` for this install, or None.

    A Clowd.Squirrel per-user install looks like::

        %LOCALAPPDATA%\\DeepAnalysisAgent\\Update.exe
        %LOCALAPPDATA%\\DeepAnalysisAgent\\app-0.4.8\\DeepAnalysisAgent.exe

    so the frozen exe sits in a versioned subdirectory and ``Update.exe``
    is one level up, next to the ``app-*`` dirs. ``Update.exe`` is the
    stable entry point: it always starts the newest installed version.

    Returns None for a dev/non-frozen run or a frozen build that was not
    installed by Squirrel (no ``Update.exe`` above the exe dir).
    """
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    candidate = exe_dir.parent / "Update.exe"
    return candidate if candidate.is_file() else None
