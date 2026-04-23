"""Shared path helpers for agent data files (config, logs, dedup DB)."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "DeepAnalysis"


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
