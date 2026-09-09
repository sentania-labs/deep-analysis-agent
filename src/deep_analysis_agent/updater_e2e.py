"""Headless installed-app entry for the Windows updater proof."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from pathlib import Path

from . import __version__, updater
from .config import AppConfig
from .paths import squirrel_update_exe
from .tray import TrayIcon


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.feed.is_dir():
        parser.error("--feed must be a local directory")

    logging.basicConfig(filename=str(args.output.with_suffix(".log")), level=logging.INFO)
    updater._UPDATE_URL = str(args.feed.resolve())
    notifications: list[str] = []
    finished = threading.Event()

    class CaptureIcon:
        def notify(self, body: str, title: str) -> None:
            notifications.append(body)
            if len(notifications) == 2:
                finished.set()

    icon = TrayIcon(config=AppConfig(), version=__version__)
    icon._icon = CaptureIcon()
    update_exe = squirrel_update_exe()
    icon._check_for_updates()
    completed = finished.wait(updater._CHECK_TIMEOUT + updater._APPLY_TIMEOUT + 30)
    args.output.write_text(
        json.dumps(
            {
                "frozen": bool(getattr(sys, "frozen", False)),
                "executable": sys.executable,
                "version": __version__,
                "update_exe": str(update_exe) if update_exe else None,
                "notifications": notifications,
                "completed": completed,
            }
        ),
        encoding="utf-8",
    )
    return 0 if completed else 1
