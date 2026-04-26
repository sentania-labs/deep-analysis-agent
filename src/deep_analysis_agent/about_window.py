"""About window — tkinter modal showing version and registration info.

Opens from the tray 'About' menu item. Runs in its own thread so the
tkinter mainloop doesn't interfere with pystray's event loop.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from typing import Any

from . import __version__
from .config import AppConfig

logger = logging.getLogger(__name__)


class AboutWindow:
    """Tkinter About dialog, displayed in a dedicated thread."""

    def __init__(
        self,
        config: AppConfig,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._on_close = on_close
        self._thread: threading.Thread | None = None
        self._root: Any = None

    def show(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="da-about",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        """Schedule ``root.destroy`` on the window's own tkinter loop."""
        root = self._root
        if root is None:
            return
        try:
            root.after(0, root.destroy)
        except Exception:
            logger.exception("Failed to schedule about window close")

    def _run(self) -> None:
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            logger.exception("tkinter unavailable — cannot open About window")
            return

        cfg = self._config
        agent_id = cfg.agent.agent_id or "Not registered"
        machine = cfg.agent.machine_name or "(unset)"
        server = cfg.server.url or "(unset)"

        root = tk.Tk()
        self._root = root
        root.title("About Deep Analysis")
        with contextlib.suppress(tk.TclError):
            root.resizable(False, False)

        frame = ttk.Frame(root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        header_font = ("TkDefaultFont", 11, "bold")
        ttk.Label(frame, text="Deep Analysis Agent", font=header_font).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        rows = (
            ("Version:", __version__),
            ("Server:", server),
            ("Agent ID:", agent_id),
            ("Machine:", machine),
        )
        for idx, (label, value) in enumerate(rows, start=1):
            ttk.Label(frame, text=label).grid(row=idx, column=0, sticky="w", padx=(0, 12), pady=2)
            ttk.Label(frame, text=value).grid(row=idx, column=1, sticky="w", pady=2)

        def _close() -> None:
            root.destroy()

        ttk.Button(frame, text="Close", command=_close).grid(
            row=len(rows) + 1, column=0, columnspan=2, pady=(12, 0)
        )

        root.protocol("WM_DELETE_WINDOW", _close)
        try:
            root.mainloop()
        except Exception:
            logger.exception("About window mainloop raised")
        finally:
            self._root = None
            if self._on_close is not None:
                try:
                    self._on_close()
                except Exception:
                    logger.exception("About window on_close callback raised")


__all__ = ["AboutWindow"]
