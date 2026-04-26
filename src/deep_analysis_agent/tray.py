"""pystray tray scaffold — idle/uploading/error states + right-click menu."""

from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from .about_window import AboutWindow
from .config import AppConfig
from .paths import config_path, logs_dir

logger = logging.getLogger(__name__)

try:  # pragma: no cover — pystray needs a display backend
    import pystray
    from PIL import Image

    _TRAY_AVAILABLE = True
except Exception:  # pragma: no cover
    pystray = None
    Image = None  # type: ignore[assignment]
    _TRAY_AVAILABLE = False


TrayState = Literal["idle", "uploading", "error", "watcher_disabled"]
_COLOR_CYCLE = ["W", "U", "B", "R", "G"]
PIP_CYCLE_SECONDS_PER_COLOR = 2.0

_STATE_LABELS: dict[str, str] = {
    "idle": "Idle",
    "uploading": "Uploading",
    "error": "Error",
    "watcher_disabled": "Watcher disabled",
}

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
    p = _icons_dir() / f"{name}.ico"
    if p.is_file():
        return Image.open(p)
    # Placeholder — solid colored square.
    rgb = _PLACEHOLDER_RGB.get(name, (128, 128, 128))
    return Image.new("RGB", (64, 64), color=rgb)


def _open_in_explorer(path: Path) -> None:
    try:
        if sys.platform == "win32":
            # Route through cmd's `start` so the per-user default-app
            # association resolves the same way Explorer's double-click does,
            # rather than os.startfile's ShellExecute path which can ignore
            # user-overridden HKCU associations for .log/.toml.
            subprocess.Popen(["start", "", str(path)], shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        logger.exception("failed to open %s", path)


class TrayIcon:
    def __init__(
        self,
        config: AppConfig,
        version: str,
        on_reregister: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._version = version
        self._on_reregister = on_reregister
        self._state: TrayState = "idle"
        self._state_lock = threading.Lock()
        self._cycle_stop = threading.Event()
        self._cycle_thread: threading.Thread | None = None
        self._icon: Any = None
        self._on_quit: Callable[[], None] | None = None
        self._sub_windows: list[Any] = []
        self._sub_windows_lock = threading.Lock()
        self._about_window: AboutWindow | None = None

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
            if state == "idle":
                self._icon.icon = _load_icon("C")
            else:
                # "error" + "watcher_disabled" both use the R (red) icon.
                self._icon.icon = _load_icon("R")
        self._refresh_menu()

    def _refresh_menu(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.update_menu()
        except Exception:
            logger.exception("update_menu failed")

    def _status_text(self, _item: Any = None) -> str:
        with self._state_lock:
            label = _STATE_LABELS.get(self._state, self._state)
        return f"Status: {label}"

    def _log_file_path(self) -> Path:
        base = self._config.logging.log_dir or logs_dir()
        return base / "agent.log"

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
                self._cycle_stop.wait(PIP_CYCLE_SECONDS_PER_COLOR)

        self._cycle_thread = threading.Thread(target=run, name="tray-cycle", daemon=True)
        self._cycle_thread.start()

    def _menu(self) -> Any:
        if pystray is None:
            return None
        items: list[Any] = [
            pystray.MenuItem(self._status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Dashboard", self._open_dashboard),
            pystray.MenuItem("Open Log", self._open_log),
            pystray.MenuItem("Settings", self._open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Check for Updates", self._check_for_updates),
            pystray.MenuItem("About", self._about),
        ]
        if self._on_reregister is not None:
            items.append(pystray.MenuItem("Re-register...", self._reregister))
        items.extend([pystray.Menu.SEPARATOR, pystray.MenuItem("Quit", self._quit)])
        return pystray.Menu(*items)

    def _reregister(self, *_: Any) -> None:
        if self._on_reregister is not None:
            self._on_reregister()

    def _open_dashboard(self, *_: Any) -> None:
        url = self._config.server.url
        try:
            webbrowser.open(url)
        except Exception:
            logger.exception("failed to open dashboard url=%s", url)

    def _open_log(self, *_: Any) -> None:
        log_file = self._log_file_path()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if not log_file.exists():
            # Open the containing directory when the log file hasn't been created yet.
            _open_in_explorer(log_file.parent)
            return
        _open_in_explorer(log_file)

    def _open_settings(self, *_: Any) -> None:
        cfg = config_path()
        if not cfg.exists():
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text("# Deep Analysis agent config\n", encoding="utf-8")
        _open_in_explorer(cfg)

    def _check_for_updates(self, *_: Any) -> None:
        message = "Squirrel checks for updates on startup and daily — no manual check needed."
        logger.info("check_for_updates_clicked note=%s", message)
        if self._icon is not None:
            try:
                self._icon.notify(message, "Deep Analysis")
            except Exception:
                logger.exception("tray notify failed")

    def _about(self, *_: Any) -> None:
        existing = self._about_window
        if existing is not None and existing._thread is not None and existing._thread.is_alive():
            return
        window = AboutWindow(
            self._config,
            on_close=lambda: self._unregister_sub_window(window),
        )
        self._about_window = window
        self._register_sub_window(window)
        window.show()

    def _register_sub_window(self, window: Any) -> None:
        with self._sub_windows_lock:
            self._sub_windows.append(window)

    def _unregister_sub_window(self, window: Any) -> None:
        with self._sub_windows_lock, contextlib.suppress(ValueError):
            self._sub_windows.remove(window)

    def _close_sub_windows(self, grace_seconds: float = 0.3) -> None:
        """Close every registered sub-window.

        ``close()`` schedules ``root.destroy`` on the window's own tkinter
        loop — calling from this thread is safe because ``tk.after`` is
        the cross-thread-safe handoff. A short grace period lets those
        destroys actually land before the interpreter exits.
        """
        with self._sub_windows_lock:
            windows = list(self._sub_windows)
        for window in windows:
            try:
                window.close()
            except Exception:
                logger.exception("Error closing sub-window %r", window)
        if windows:
            time.sleep(grace_seconds)

    def _quit(self, *_: Any) -> None:
        self._cycle_stop.set()
        self._close_sub_windows()
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
