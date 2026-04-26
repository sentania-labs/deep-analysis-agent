"""Log viewer window — tkinter UI for reading agent.log in-app.

Opens from the tray 'Open Log' menu item. Runs in its own thread so
the tkinter mainloop doesn't interfere with pystray's event loop.
Supports level filtering, refresh, copy-to-clipboard, save-as, and
a fallback 'Open raw file' button that shells out to the OS handler.
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


LEVELS = ("All", "DEBUG", "INFO", "WARNING", "ERROR")


def _open_in_editor(path: Path) -> None:
    if not path.exists():
        logger.warning("log viewer open-raw target missing: %s", path)
        return
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607


def _read_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    except OSError:
        logger.exception("Failed to read log file %s", path)
        return ""


def filter_lines(content: str, level: str) -> str:
    """Keep only lines whose text contains ``level`` (substring match).

    ``level == "All"`` returns content unchanged. Empty content passes
    through untouched so the 'not found' placeholder is preserved.
    """
    if level == "All" or not content:
        return content
    keep = [line for line in content.splitlines(keepends=True) if level in line]
    return "".join(keep)


class LogViewerWindow:
    """Tkinter log viewer, displayed in a dedicated thread."""

    def __init__(
        self,
        log_file: Path | None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._log_file = log_file
        self._on_close = on_close
        self._thread: threading.Thread | None = None
        self._root: Any = None

    def show(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="da-log-viewer",
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
            logger.exception("Failed to schedule log viewer close")

    def _run(self) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog, messagebox, scrolledtext, ttk
        except ImportError:
            logger.exception("tkinter unavailable — cannot open Log Viewer window")
            return

        log_path = self._log_file

        root = tk.Tk()
        self._root = root
        root.title("Deep Analysis — Log Viewer")
        with contextlib.suppress(tk.TclError):
            root.geometry("800x500")
            root.minsize(480, 240)

        toolbar = ttk.Frame(root, padding=(8, 6))
        toolbar.pack(fill="x")

        ttk.Label(toolbar, text="Level:").pack(side="left", padx=(0, 4))
        level_var = tk.StringVar(value="All")
        level_combo = ttk.Combobox(
            toolbar,
            textvariable=level_var,
            values=LEVELS,
            state="readonly",
            width=10,
        )
        level_combo.pack(side="left", padx=(0, 8))

        text = scrolledtext.ScrolledText(root, wrap="none")
        text.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        text.configure(state="disabled")

        current_content = {"value": ""}

        def _render(content: str) -> None:
            filtered = filter_lines(content, level_var.get())
            text.configure(state="normal")
            text.delete("1.0", "end")
            if filtered:
                text.insert("1.0", filtered)
            elif log_path is None or not log_path.exists():
                text.insert("1.0", "Log file not found.")
            text.configure(state="disabled")
            text.see("end")

        def _refresh() -> None:
            if log_path is None:
                current_content["value"] = ""
            else:
                current_content["value"] = _read_log(log_path)
            _render(current_content["value"])

        def _on_level_change(_event: Any = None) -> None:
            _render(current_content["value"])

        level_combo.bind("<<ComboboxSelected>>", _on_level_change)

        def _copy() -> None:
            content = current_content["value"]
            try:
                root.clipboard_clear()
                root.clipboard_append(content)
                root.update()
            except tk.TclError:
                logger.exception("Failed to copy log to clipboard")

        def _save_as() -> None:
            default_name = log_path.name if log_path is not None else "agent.log"
            target = filedialog.asksaveasfilename(
                parent=root,
                title="Save log as",
                defaultextension=".log",
                initialfile=default_name,
                filetypes=[("Log files", "*.log"), ("All files", "*.*")],
            )
            if not target:
                return
            try:
                Path(target).write_text(current_content["value"], encoding="utf-8")
            except OSError as exc:
                logger.exception("Failed to save log copy")
                messagebox.showerror(
                    "Save failed",
                    f"Could not save log: {exc}",
                    parent=root,
                )

        def _open_raw() -> None:
            if log_path is None:
                messagebox.showinfo(
                    "Open raw file",
                    "No log file path is configured.",
                    parent=root,
                )
                return
            if not log_path.exists():
                messagebox.showinfo(
                    "Open raw file",
                    "Log file not found.",
                    parent=root,
                )
                return
            _open_in_editor(log_path)

        def _close() -> None:
            root.destroy()

        ttk.Button(toolbar, text="Refresh", command=_refresh).pack(side="left", padx=(0, 4))
        ttk.Button(toolbar, text="Copy", command=_copy).pack(side="left", padx=(0, 4))
        ttk.Button(toolbar, text="Save as…", command=_save_as).pack(side="left", padx=(0, 4))
        ttk.Button(toolbar, text="Open raw file", command=_open_raw).pack(side="left", padx=(0, 4))
        ttk.Button(toolbar, text="Close", command=_close).pack(side="right")

        _refresh()

        root.protocol("WM_DELETE_WINDOW", _close)
        try:
            root.mainloop()
        except Exception:
            logger.exception("Log viewer mainloop raised")
        finally:
            self._root = None
            if self._on_close is not None:
                try:
                    self._on_close()
                except Exception:
                    logger.exception("Log viewer on_close callback raised")


__all__ = ["LogViewerWindow", "filter_lines"]
