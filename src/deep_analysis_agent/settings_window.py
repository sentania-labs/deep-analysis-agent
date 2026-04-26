"""Settings window — tkinter UI for editing AppConfig.

Opens from the tray 'Settings' menu item. Runs in its own thread so
the tkinter mainloop doesn't interfere with pystray's event loop. On
Save, validates fields, writes config atomically (DPAPI-wrapping the
api_token), and invokes an ``on_save`` callback so the tray can hot-
reload without restart.
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import (
    AgentSettings,
    AppConfig,
    LoggingSettings,
    MTGOSettings,
    ServerSettings,
    _default_mtgo_log_dir,
    save_config,
)
from .paths import config_path

logger = logging.getLogger(__name__)


_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_LOG_FORMATS = ("plaintext", "json")


def normalize_server_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def validate_form(*, url: str, heartbeat_interval: int) -> str | None:
    """Return an error message if the form is invalid, else None."""
    if not url.strip():
        return "Server URL is required."
    if heartbeat_interval <= 0:
        return "Heartbeat interval must be a positive integer (seconds)."
    return None


def build_config(
    original: AppConfig,
    *,
    server_url: str,
    tls_verify: bool,
    machine_name: str,
    heartbeat_interval: int,
    log_dir: str,
    log_level: str,
    log_format: str,
    log_stderr: bool,
) -> AppConfig:
    """Build a new ``AppConfig`` from form values, carrying forward unedited fields."""
    return AppConfig(
        server=ServerSettings(
            url=normalize_server_url(server_url),
            tls_verify=tls_verify,
        ),
        agent=AgentSettings(
            machine_name=machine_name.strip(),
            agent_id=original.agent.agent_id,
            api_token=original.agent.api_token,
            registered_at=original.agent.registered_at,
            heartbeat_interval_seconds=heartbeat_interval,
        ),
        mtgo=MTGOSettings(
            log_dir=Path(log_dir.strip()) if log_dir.strip() else original.mtgo.log_dir,
            watched_suffixes=list(original.mtgo.watched_suffixes),
            stability_seconds=original.mtgo.stability_seconds,
        ),
        logging=LoggingSettings(
            level=log_level,
            log_dir=original.logging.log_dir,
            stderr=log_stderr,
            format=log_format,
        ),
    )


def _open_in_editor(path: Path) -> None:
    if not path.exists():
        logger.warning("settings open-raw target missing: %s", path)
        return
    if sys.platform == "win32":
        subprocess.Popen(["start", "", str(path)], shell=True)  # noqa: S602,S607
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607


class SettingsWindow:
    """Tkinter settings dialog, displayed in a dedicated thread."""

    def __init__(
        self,
        config: AppConfig,
        on_save: Callable[[], None],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._on_save = on_save
        self._on_close = on_close
        self._thread: threading.Thread | None = None
        self._root: Any = None

    def show(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="da-settings",
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
            logger.exception("Failed to schedule settings window close")

    def _run(self) -> None:  # pragma: no cover — UI thread, requires display
        try:
            import tkinter as tk
            from tkinter import filedialog, messagebox, ttk
        except ImportError:
            logger.exception("tkinter unavailable — cannot open Settings window")
            return

        cfg = self._config

        root = tk.Tk()
        self._root = root
        root.title("Deep Analysis — Settings")
        with contextlib.suppress(tk.TclError):
            root.minsize(560, 0)

        url_var = tk.StringVar(value=cfg.server.url)
        raw_tls = cfg.server.tls_verify
        tls_default = bool(raw_tls) if isinstance(raw_tls, bool) else True
        tls_var = tk.BooleanVar(value=tls_default)
        machine_var = tk.StringVar(value=cfg.agent.machine_name)
        heartbeat_var = tk.IntVar(value=max(1, int(cfg.agent.heartbeat_interval_seconds)))
        agent_id_text = cfg.agent.agent_id or "(not registered)"
        log_dir_var = tk.StringVar(value=str(cfg.mtgo.log_dir))
        log_level_var = tk.StringVar(value=cfg.logging.level.upper())
        log_format_var = tk.StringVar(value=cfg.logging.format.lower())
        log_stderr_var = tk.BooleanVar(value=bool(cfg.logging.stderr))

        frame = ttk.Frame(root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        header_font = ("TkDefaultFont", 10, "bold")

        row = 0
        ttk.Label(frame, text="Server", font=header_font).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        ttk.Label(frame, text="Server URL:").grid(row=row, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(frame, textvariable=url_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=2
        )
        row += 1
        ttk.Checkbutton(frame, text="Verify TLS certificate", variable=tls_var).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=2
        )
        row += 1
        ttk.Separator(frame).grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1

        ttk.Label(frame, text="Agent", font=header_font).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        ttk.Label(frame, text="Machine name:").grid(row=row, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(frame, textvariable=machine_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=2
        )
        row += 1
        ttk.Label(frame, text="Heartbeat interval (s):").grid(
            row=row, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Spinbox(frame, from_=1, to=86400, textvariable=heartbeat_var, width=8).grid(
            row=row, column=1, sticky="w", pady=2
        )
        row += 1
        ttk.Label(frame, text="Agent ID:").grid(row=row, column=0, sticky="w", padx=(0, 8))
        ttk.Label(frame, text=agent_id_text, foreground="#666").grid(
            row=row, column=1, columnspan=2, sticky="w", pady=2
        )
        row += 1
        ttk.Separator(frame).grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1

        ttk.Label(frame, text="MTGO", font=header_font).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        ttk.Label(frame, text="Log directory:").grid(row=row, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(frame, textvariable=log_dir_var).grid(row=row, column=1, sticky="ew", pady=2)

        def _browse() -> None:
            start_dir = log_dir_var.get() or str(Path.home())
            selected = filedialog.askdirectory(initialdir=start_dir, parent=root)
            if selected:
                log_dir_var.set(selected)

        ttk.Button(frame, text="Browse…", command=_browse).grid(
            row=row, column=2, sticky="e", padx=(4, 0)
        )
        row += 1

        def _auto_detect() -> None:
            detected = _default_mtgo_log_dir()
            log_dir_var.set(str(detected))

        ttk.Button(frame, text="Auto-detect", command=_auto_detect).grid(
            row=row, column=1, sticky="w", pady=2
        )
        row += 1
        ttk.Separator(frame).grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1

        ttk.Label(frame, text="Logging", font=header_font).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        ttk.Label(frame, text="Level:").grid(row=row, column=0, sticky="w", padx=(0, 8))
        ttk.Combobox(
            frame,
            textvariable=log_level_var,
            values=_LOG_LEVELS,
            state="readonly",
            width=12,
        ).grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        ttk.Label(frame, text="Format:").grid(row=row, column=0, sticky="w", padx=(0, 8))
        ttk.Combobox(
            frame,
            textvariable=log_format_var,
            values=_LOG_FORMATS,
            state="readonly",
            width=12,
        ).grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        ttk.Checkbutton(frame, text="Also log to stderr", variable=log_stderr_var).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=2
        )
        row += 1
        ttk.Separator(frame).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        def _save() -> None:
            try:
                heartbeat = int(heartbeat_var.get())
            except (ValueError, tk.TclError):
                messagebox.showerror(
                    "Invalid input",
                    "Heartbeat interval must be a positive integer.",
                    parent=root,
                )
                return

            err = validate_form(url=url_var.get(), heartbeat_interval=heartbeat)
            if err is not None:
                messagebox.showerror("Invalid input", err, parent=root)
                return

            new_config = build_config(
                cfg,
                server_url=url_var.get(),
                tls_verify=bool(tls_var.get()),
                machine_name=machine_var.get(),
                heartbeat_interval=heartbeat,
                log_dir=log_dir_var.get(),
                log_level=log_level_var.get(),
                log_format=log_format_var.get(),
                log_stderr=bool(log_stderr_var.get()),
            )
            try:
                save_config(new_config)
            except Exception as exc:
                logger.exception("Failed to save config")
                messagebox.showerror(
                    "Save failed",
                    f"Could not save config: {exc}",
                    parent=root,
                )
                return
            try:
                self._on_save()
            except Exception:
                logger.exception("Settings on_save callback raised")
            root.destroy()

        def _cancel() -> None:
            root.destroy()

        def _open_raw() -> None:
            target = config_path()
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# Deep Analysis agent config\n", encoding="utf-8")
            _open_in_editor(target)

        button_row = ttk.Frame(frame)
        button_row.grid(row=row, column=0, columnspan=3, sticky="ew")
        button_row.columnconfigure(0, weight=1)
        ttk.Button(button_row, text="Open config file", command=_open_raw).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(button_row, text="Cancel", command=_cancel).grid(
            row=0, column=1, sticky="e", padx=(0, 6)
        )
        ttk.Button(button_row, text="Save", command=_save).grid(row=0, column=2, sticky="e")

        root.protocol("WM_DELETE_WINDOW", _cancel)
        try:
            root.mainloop()
        except Exception:
            logger.exception("Settings window mainloop raised")
        finally:
            self._root = None
            if self._on_close is not None:
                try:
                    self._on_close()
                except Exception:
                    logger.exception("Settings on_close callback raised")


def detect_default_mtgo_log_dir() -> Path:
    """Return the platform-default MTGO log directory."""
    return _default_mtgo_log_dir()


__all__ = [
    "SettingsWindow",
    "build_config",
    "detect_default_mtgo_log_dir",
    "normalize_server_url",
    "validate_form",
]
