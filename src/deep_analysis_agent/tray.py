"""pystray tray scaffold — idle/uploading/error states + right-click menu."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from .config import AppConfig
from .paths import config_path, logs_dir

logger = logging.getLogger(__name__)

try:  # pragma: no cover — pystray needs a display backend
    import pystray  # type: ignore[import-untyped]
    from PIL import Image

    _TRAY_AVAILABLE = True
except Exception:  # pragma: no cover
    pystray = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    _TRAY_AVAILABLE = False


TrayState = Literal["idle", "uploading", "error"]
_COLOR_CYCLE = ["W", "U", "B", "R", "G"]
_CYCLE_SECONDS = 2.0

_PLACEHOLDER_RGB = {
    "W": (245, 245, 230),
    "U": (14, 104, 171),
    "B": (40, 40, 40),
    "R": (211, 32, 42),
    "G": (0, 115, 62),
    "C": (193, 193, 193),
}


def _icons_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "icons"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent / "icons"


def _load_icon(name: str) -> Any:
    if Image is None:
        return None
    p = _icons_dir() / f"{name}.png"
    if p.is_file():
        return Image.open(p)
    # Placeholder — solid colored square.
    rgb = _PLACEHOLDER_RGB.get(name, (128, 128, 128))
    return Image.new("RGB", (64, 64), color=rgb)


def _open_in_explorer(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        logger.exception("failed to open %s", path)


class TrayIcon:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._state: TrayState = "idle"
        self._state_lock = threading.Lock()
        self._cycle_stop = threading.Event()
        self._cycle_thread: threading.Thread | None = None
        self._icon: Any = None
        self._on_quit: Callable[[], None] | None = None

    def set_state(self, state: TrayState) -> None:
        with self._state_lock:
            if state == self._state:
                return
            self._state = state
        if self._icon is None:
            return
        if state == "uploading":
            self._start_cycle()
        else:
            self._cycle_stop.set()
            self._icon.icon = _load_icon("C" if state == "idle" else "R")

    def _start_cycle(self) -> None:
        if self._cycle_thread is not None and self._cycle_thread.is_alive():
            return
        self._cycle_stop.clear()

        def run() -> None:
            i = 0
            while not self._cycle_stop.is_set():
                name = _COLOR_CYCLE[i % len(_COLOR_CYCLE)]
                if self._icon is not None:
                    self._icon.icon = _load_icon(name)
                i += 1
                self._cycle_stop.wait(_CYCLE_SECONDS)

        self._cycle_thread = threading.Thread(target=run, name="tray-cycle", daemon=True)
        self._cycle_thread.start()

    def _menu(self) -> Any:
        if pystray is None:
            return None
        return pystray.Menu(
            pystray.MenuItem("Open logs folder", self._open_logs),
            pystray.MenuItem("Settings", self._open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _open_logs(self, *_: Any) -> None:
        target = self._config.logging.log_dir or logs_dir()
        target.mkdir(parents=True, exist_ok=True)
        _open_in_explorer(target)

    def _open_settings(self, *_: Any) -> None:
        cfg = config_path()
        if not cfg.exists():
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text("# Deep Analysis agent config\n", encoding="utf-8")
        _open_in_explorer(cfg)

    def _quit(self, *_: Any) -> None:
        self._cycle_stop.set()
        if self._icon is not None:
            self._icon.stop()
        if self._on_quit is not None:
            self._on_quit()

    def start(self, on_quit: Callable[[], None]) -> None:
        if not _TRAY_AVAILABLE or pystray is None:
            raise RuntimeError("pystray is not available in this environment")
        self._on_quit = on_quit
        self._icon = pystray.Icon(
            "deep-analysis-agent",
            icon=_load_icon("C"),
            title="Deep Analysis",
            menu=self._menu(),
        )
        self._icon.run()  # blocks

    def stop(self) -> None:
        self._cycle_stop.set()
        if self._icon is not None:
            self._icon.stop()
