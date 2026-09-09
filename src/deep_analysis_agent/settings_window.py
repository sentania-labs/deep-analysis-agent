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

from pydantic import BaseModel

from . import autostart
from .config import (
    AppConfig,
    _default_mtgo_log_dir,
    save_config,
)
from .paths import config_path

logger = logging.getLogger(__name__)


_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_LOG_FORMATS = ("plaintext", "json")
_MIN_STABILITY_SECONDS = 600.0


def normalize_server_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def parse_lines(value: str) -> list[str]:
    """Return non-empty, trimmed lines from a multiline form field."""
    return [line.strip() for line in value.splitlines() if line.strip()]


def validate_form(
    *,
    url: str,
    heartbeat_interval: int,
    watched_suffixes: list[str] | None = None,
    watched_name_globs: list[str] | None = None,
    stability_seconds: float | None = None,
    card_data_source_enabled: bool = False,
    card_data_source_auto_detect: bool = False,
    card_data_source_dir: str = "",
) -> str | None:
    """Return an error message if the form is invalid, else None."""
    if not url.strip():
        return "Server URL is required."
    if heartbeat_interval <= 0:
        return "Heartbeat interval must be a positive integer (seconds)."
    if watched_suffixes is not None and not watched_suffixes:
        return "At least one watched file suffix is required."
    if watched_name_globs is not None and not watched_name_globs:
        return "At least one watched name glob is required."
    if stability_seconds is not None and stability_seconds < _MIN_STABILITY_SECONDS:
        return "Stability wait must be at least 600 seconds."
    if (
        card_data_source_enabled
        and not card_data_source_auto_detect
        and not card_data_source_dir.strip()
    ):
        return "Choose a CardDataSource directory or disable card data uploads."
    return None


def _tls_verify_value(enabled: bool, ca_bundle: str) -> bool | str:
    """Return the HTTP client TLS setting represented by the form controls."""
    if not enabled:
        return False
    return ca_bundle.strip() or True


def _updated[M: BaseModel](model: M, **edits: Any) -> M:
    """Return a copy of ``model`` with only ``edits`` replaced.

    Every field the caller does not name is carried forward untouched, so a
    field added to a config model later cannot be silently reset on save.

    Note: ``model_copy`` does not re-run validators. Values carried forward
    were validated when the config was loaded, but a future caller editing a
    validated field (``stability_seconds``, for one) must validate it here.
    """
    return model.model_copy(update=edits)


def build_config(
    original: AppConfig,
    *,
    server_url: str,
    tls_verify: bool,
    tls_ca_bundle: str,
    machine_name: str,
    heartbeat_interval: int,
    log_dir: str,
    watched_suffixes: list[str],
    watched_name_globs: list[str],
    stability_seconds: float,
    card_data_source_enabled: bool,
    card_data_source_auto_detect: bool,
    card_data_source_dir: str,
    log_level: str,
    logging_dir: str,
    log_format: str,
    log_stderr: bool,
) -> AppConfig:
    """Build a new ``AppConfig`` from form values, carrying forward unedited fields.

    Only fields the settings form actually edits are replaced; everything else
    in ``original`` is copied through verbatim.
    """
    return _updated(
        original,
        server=_updated(
            original.server,
            url=normalize_server_url(server_url),
            tls_verify=_tls_verify_value(tls_verify, tls_ca_bundle),
        ),
        agent=_updated(
            original.agent,
            machine_name=machine_name.strip(),
            heartbeat_interval_seconds=heartbeat_interval,
        ),
        mtgo=_updated(
            original.mtgo,
            log_dir=Path(log_dir.strip()) if log_dir.strip() else original.mtgo.log_dir,
            watched_suffixes=watched_suffixes,
            watched_name_globs=watched_name_globs,
            stability_seconds=stability_seconds,
            card_data_source_enabled=card_data_source_enabled,
            card_data_source_dir=(
                None
                if card_data_source_auto_detect
                else Path(card_data_source_dir.strip())
                if card_data_source_dir.strip()
                else None
            ),
        ),
        logging=_updated(
            original.logging,
            level=log_level,
            log_dir=Path(logging_dir.strip()) if logging_dir.strip() else None,
            stderr=log_stderr,
            format=log_format,
        ),
    )


def apply_autostart_change(desired: bool) -> str | None:
    """Sync the registry-backed autostart state to ``desired``.

    Returns ``None`` on success or no-op, or a user-facing error message
    if the underlying ``autostart`` call reported failure.
    """
    current = autostart.is_enabled()
    if desired == current:
        return None
    if desired:
        if autostart.enable():
            return None
        return "Could not enable Start with Windows. Check the agent log for details."
    if autostart.disable():
        return None
    return "Could not disable Start with Windows. Check the agent log for details."


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
        initial_card_data = (cfg.mtgo.card_data_source_enabled, cfg.mtgo.card_data_source_dir)

        root = tk.Tk()
        self._root = root
        root.title("Deep Analysis — Settings")
        with contextlib.suppress(tk.TclError):
            root.minsize(560, 480)

        url_var = tk.StringVar(value=cfg.server.url)
        raw_tls = cfg.server.tls_verify
        tls_default = bool(raw_tls) if isinstance(raw_tls, bool) else True
        tls_var = tk.BooleanVar(value=tls_default)
        tls_ca_var = tk.StringVar(value=raw_tls if isinstance(raw_tls, str) else "")
        machine_var = tk.StringVar(value=cfg.agent.machine_name)
        heartbeat_var = tk.IntVar(value=max(1, int(cfg.agent.heartbeat_interval_seconds)))
        autostart_var = tk.BooleanVar(value=autostart.is_enabled())
        agent_id_text = cfg.agent.agent_id or "(not registered)"
        log_dir_var = tk.StringVar(value=str(cfg.mtgo.log_dir))
        watched_suffixes_text = "\n".join(cfg.mtgo.watched_suffixes)
        watched_name_globs_text = "\n".join(cfg.mtgo.watched_name_globs)
        stability_var = tk.StringVar(value=str(cfg.mtgo.stability_seconds))
        card_data_source_enabled_var = tk.BooleanVar(value=cfg.mtgo.card_data_source_enabled)
        card_data_source_auto_detect_var = tk.BooleanVar(
            value=cfg.mtgo.card_data_source_dir is None
        )
        card_data_source_dir_var = tk.StringVar(
            value=str(cfg.mtgo.card_data_source_dir) if cfg.mtgo.card_data_source_dir else ""
        )
        log_level_var = tk.StringVar(value=cfg.logging.level.upper())
        logging_dir_var = tk.StringVar(
            value=str(cfg.logging.log_dir) if cfg.logging.log_dir else ""
        )
        log_format_var = tk.StringVar(value=cfg.logging.format.lower())
        log_stderr_var = tk.BooleanVar(value=bool(cfg.logging.stderr))
        validation_var = tk.StringVar(value="")

        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        canvas = tk.Canvas(root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        frame = ttk.Frame(canvas, padding=12)
        frame_window = canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.columnconfigure(1, weight=1)

        def _resize_scroll_region(_event: Any) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _resize_frame(event: Any) -> None:
            canvas.itemconfigure(frame_window, width=event.width)

        def _scroll(event: Any) -> str:
            canvas.yview_scroll(int(-event.delta / 120), "units")
            return "break"

        frame.bind("<Configure>", _resize_scroll_region)
        canvas.bind("<Configure>", _resize_frame)
        canvas.bind_all("<MouseWheel>", _scroll)
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
        ttk.Label(frame, text="Custom CA bundle:").grid(row=row, column=0, sticky="w", padx=(0, 8))
        tls_ca_entry = ttk.Entry(frame, textvariable=tls_ca_var)
        tls_ca_entry.grid(row=row, column=1, sticky="ew", pady=2)

        def _browse_tls_ca() -> None:
            selected = filedialog.askopenfilename(
                initialdir=str(Path(tls_ca_var.get()).parent) if tls_ca_var.get() else None,
                parent=root,
                title="Choose CA bundle",
            )
            if selected:
                tls_ca_var.set(selected)

        ttk.Button(frame, text="Browse...", command=_browse_tls_ca).grid(
            row=row, column=2, sticky="e", padx=(4, 0)
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
        ttk.Checkbutton(frame, text="Start with Windows on login", variable=autostart_var).grid(
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

        ttk.Button(frame, text="Browse...", command=_browse).grid(
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

        advanced = ttk.LabelFrame(frame, text="Advanced MTGO", padding=8)
        advanced.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        advanced.columnconfigure(1, weight=1)
        ttk.Label(advanced, text="Watched suffixes:").grid(
            row=0, column=0, sticky="nw", padx=(0, 8)
        )
        watched_suffixes_widget = tk.Text(advanced, height=3, width=36, wrap="none")
        watched_suffixes_widget.insert("1.0", watched_suffixes_text)
        watched_suffixes_widget.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Label(advanced, text="One file suffix per line", foreground="#666").grid(
            row=1, column=1, columnspan=2, sticky="w"
        )
        ttk.Label(advanced, text="Watched name globs:").grid(
            row=2, column=0, sticky="nw", padx=(0, 8), pady=(6, 0)
        )
        watched_name_globs_widget = tk.Text(advanced, height=3, width=36, wrap="none")
        watched_name_globs_widget.insert("1.0", watched_name_globs_text)
        watched_name_globs_widget.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(6, 2))
        ttk.Label(advanced, text="One filename pattern per line", foreground="#666").grid(
            row=3, column=1, columnspan=2, sticky="w"
        )
        ttk.Label(advanced, text="Stability wait (s):").grid(
            row=4, column=0, sticky="w", padx=(0, 8), pady=(6, 0)
        )
        ttk.Spinbox(
            advanced,
            from_=_MIN_STABILITY_SECONDS,
            to=86400,
            increment=60,
            textvariable=stability_var,
            width=10,
        ).grid(row=4, column=1, sticky="w", pady=(6, 0))
        ttk.Checkbutton(
            advanced,
            text="Upload MTGO card data",
            variable=card_data_source_enabled_var,
        ).grid(row=5, column=1, columnspan=2, sticky="w", pady=(8, 2))
        card_data_source_auto_detect = ttk.Checkbutton(
            advanced,
            text="Auto-detect from MTGO log directory",
            variable=card_data_source_auto_detect_var,
        )
        card_data_source_auto_detect.grid(row=6, column=1, columnspan=2, sticky="w", pady=2)
        ttk.Label(advanced, text="CardDataSource directory:").grid(
            row=7, column=0, sticky="w", padx=(0, 8)
        )
        card_data_source_dir_entry = ttk.Entry(advanced, textvariable=card_data_source_dir_var)
        card_data_source_dir_entry.grid(row=7, column=1, sticky="ew", pady=2)

        def _browse_card_data_source() -> None:
            start_dir = card_data_source_dir_var.get() or log_dir_var.get() or str(Path.home())
            selected = filedialog.askdirectory(initialdir=start_dir, parent=root)
            if selected:
                card_data_source_dir_var.set(selected)

        card_data_source_browse = ttk.Button(
            advanced, text="Browse...", command=_browse_card_data_source
        )
        card_data_source_browse.grid(row=7, column=2, sticky="e", padx=(4, 0))

        def _sync_card_data_source_state(*_args: Any) -> None:
            enabled = bool(card_data_source_enabled_var.get())
            card_data_source_auto_detect.configure(state="normal" if enabled else "disabled")
            directory_state = (
                "normal" if enabled and not card_data_source_auto_detect_var.get() else "disabled"
            )
            card_data_source_dir_entry.configure(state=directory_state)
            card_data_source_browse.configure(state=directory_state)

        card_data_source_enabled_var.trace_add("write", _sync_card_data_source_state)
        card_data_source_auto_detect_var.trace_add("write", _sync_card_data_source_state)
        _sync_card_data_source_state()
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
        ttk.Label(frame, text="Log directory:").grid(row=row, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(frame, textvariable=logging_dir_var).grid(row=row, column=1, sticky="ew", pady=2)

        def _browse_logging_dir() -> None:
            start_dir = logging_dir_var.get() or str(Path.home())
            selected = filedialog.askdirectory(initialdir=start_dir, parent=root)
            if selected:
                logging_dir_var.set(selected)

        ttk.Button(frame, text="Browse...", command=_browse_logging_dir).grid(
            row=row, column=2, sticky="e", padx=(4, 0)
        )
        row += 1
        ttk.Checkbutton(frame, text="Also log to stderr", variable=log_stderr_var).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=2
        )
        row += 1
        ttk.Separator(frame).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1

        validation_label = ttk.Label(
            frame,
            textvariable=validation_var,
            foreground="#b00020",
            wraplength=520,
        )
        validation_label.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1
        save_notice_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=save_notice_var, wraplength=520).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
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

            try:
                stability_seconds = float(stability_var.get())
            except (ValueError, tk.TclError):
                validation_var.set("Stability wait must be a number of seconds.")
                return

            watched_suffixes = parse_lines(watched_suffixes_widget.get("1.0", "end"))
            watched_name_globs = parse_lines(watched_name_globs_widget.get("1.0", "end"))

            err = validate_form(
                url=url_var.get(),
                heartbeat_interval=heartbeat,
                watched_suffixes=watched_suffixes,
                watched_name_globs=watched_name_globs,
                stability_seconds=stability_seconds,
                card_data_source_enabled=bool(card_data_source_enabled_var.get()),
                card_data_source_auto_detect=bool(card_data_source_auto_detect_var.get()),
                card_data_source_dir=card_data_source_dir_var.get(),
            )
            if err is not None:
                validation_var.set(err)
                return
            validation_var.set("")

            new_config = build_config(
                cfg,
                server_url=url_var.get(),
                tls_verify=bool(tls_var.get()),
                tls_ca_bundle=tls_ca_var.get(),
                machine_name=machine_var.get(),
                heartbeat_interval=heartbeat,
                log_dir=log_dir_var.get(),
                watched_suffixes=watched_suffixes,
                watched_name_globs=watched_name_globs,
                stability_seconds=stability_seconds,
                card_data_source_enabled=bool(card_data_source_enabled_var.get()),
                card_data_source_auto_detect=bool(card_data_source_auto_detect_var.get()),
                card_data_source_dir=card_data_source_dir_var.get(),
                log_level=log_level_var.get(),
                logging_dir=logging_dir_var.get(),
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
            autostart_err = apply_autostart_change(bool(autostart_var.get()))
            if autostart_err is not None:
                messagebox.showwarning("Autostart", autostart_err, parent=root)
            try:
                self._on_save()
            except Exception:
                logger.exception("Settings on_save callback raised")
            if initial_card_data != (
                new_config.mtgo.card_data_source_enabled,
                new_config.mtgo.card_data_source_dir,
            ):
                save_notice_var.set(
                    "Settings saved. CardDataSource changes apply after the agent restarts."
                )
                cancel_button.configure(text="Close")
                root.update_idletasks()
                canvas.yview_moveto(1.0)
                return
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
        cancel_button = ttk.Button(button_row, text="Cancel", command=_cancel)
        cancel_button.grid(row=0, column=1, sticky="e", padx=(0, 6))
        ttk.Button(button_row, text="Save", command=_save).grid(row=0, column=2, sticky="e")

        root.protocol("WM_DELETE_WINDOW", _cancel)
        root.update_idletasks()
        available_height = max(480, root.winfo_screenheight() - 100)
        root.geometry(f"600x{min(frame.winfo_reqheight(), available_height)}")
        try:
            root.mainloop()
        except Exception:
            logger.exception("Settings window mainloop raised")
        finally:
            with contextlib.suppress(Exception):
                canvas.unbind_all("<MouseWheel>")
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
    "apply_autostart_change",
    "build_config",
    "detect_default_mtgo_log_dir",
    "normalize_server_url",
    "parse_lines",
    "validate_form",
]
