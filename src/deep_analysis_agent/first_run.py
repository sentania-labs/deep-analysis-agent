"""First-run registration flow.

Prompts the user for credentials or a registration code (via tkinter if
available, falling back to stdin), exchanges them with the server, saves
the resulting `api_token` (DPAPI-wrapped) and `agent_id` to the config
TOML, and returns True on success.

Returns False if the user cancels, or if registration fails after the
user explicitly gives up. The caller (main) exits cleanly on False.

Two rules govern the UI in here, both because the shipped agent is a tray
app with no console attached:

1. Failures are reported through a tkinter message box whenever one can
   be shown. `print()` is a fallback for the headless case only, never
   the primary user-visible channel.
2. "The user cancelled a dialog" and "tkinter is unavailable" are
   different conditions and are never conflated. Only the second one may
   fall back to stdin. Falling back after a cancel would leave a GUI app
   blocked on a read from a console nobody is looking at.

"tkinter is unavailable" is defined narrowly and in exactly one place
(`_tk_root`): the import fails, or a root window cannot be created. Once
a root window exists there is a working GUI, so anything that goes wrong
after that is treated as a decline. It is not a licence to read stdin.
"""

from __future__ import annotations

import asyncio
import platform
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from . import __version__, auth
from .config import AppConfig, _default_mtgo_log_dir, save_config

logger = structlog.get_logger(__name__)


class _TkUnavailable:
    """Sentinel: tkinter itself could not be used.

    Distinct from `None`, which means the user saw a dialog and declined.
    Only this sentinel may trigger the stdin fallback.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "<tkinter unavailable>"


TK_UNAVAILABLE = _TkUnavailable()


def _tk_root(*, withdraw: bool = True) -> Any | None:
    """Import tkinter and create a root window. None if tkinter is unusable.

    This is the single definition of "tkinter is unavailable": the import
    fails, or no root window can be made (no display, no session). Callers
    turn a None into TK_UNAVAILABLE and only then consider stdin.
    """
    try:
        import tkinter as tk
    except ImportError:
        return None

    try:
        root = tk.Tk()
        if withdraw:
            root.withdraw()
    except Exception:
        logger.exception("tkinter_root_failed")
        return None
    return root


def _destroy(root: Any) -> None:
    """Destroy a root window without letting teardown mask the real error."""
    try:
        root.destroy()
    except Exception:
        logger.exception("tkinter_root_destroy_failed")


def _default_machine_name() -> str:
    try:
        return socket.gethostname() or platform.node() or "unknown"
    except Exception:
        return "unknown"


def _prompt_code_tk() -> str | None | _TkUnavailable:
    """Show a tkinter dialog asking for the registration code.

    Returns the entered code stripped of whitespace, None if the user
    cancelled or submitted a blank code, or TK_UNAVAILABLE if tkinter
    could not be used at all.
    """
    root = _tk_root()
    if root is None:
        return TK_UNAVAILABLE

    try:
        from tkinter import simpledialog

        code = simpledialog.askstring(
            "Deep Analysis — Register",
            "Paste your registration code (XXXX-XXXX):",
        )
    except Exception:
        logger.exception("tkinter dialog failed")
        return None
    finally:
        _destroy(root)

    if code is None:
        return None
    return code.strip() or None


def _prompt_code_stdin() -> str | None:
    print("Deep Analysis — first-run registration")
    print("Paste the registration code from the web UI (or blank to cancel):")
    try:
        code = input("> ").strip()
    except EOFError:
        return None
    if not code:
        return None
    return code


def _prompt_code() -> str | None:
    tk_result = _prompt_code_tk()
    if isinstance(tk_result, _TkUnavailable):
        return _prompt_code_stdin()
    return tk_result


def _prompt_method_tk() -> int | None | _TkUnavailable:
    """Ask the user which registration method to use via a tkinter radio-button dialog.

    Returns 1 for email/password, 2 for registration code, None if the
    user cancelled, or TK_UNAVAILABLE if tkinter could not be used.
    """
    root = _tk_root(withdraw=False)
    if root is None:
        return TK_UNAVAILABLE

    result: list[int | None] = [None]

    try:
        import tkinter as tk
        from tkinter import ttk

        root.title("Deep Analysis — Register")
        root.resizable(False, False)

        frame = ttk.Frame(root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text="How would you like to register?",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        method_var = tk.IntVar(value=1)

        ttk.Radiobutton(
            frame,
            text="Sign in with email + password",
            variable=method_var,
            value=1,
        ).grid(row=1, column=0, sticky="w", pady=2)

        ttk.Radiobutton(
            frame,
            text="Use registration code",
            variable=method_var,
            value=2,
        ).grid(row=2, column=0, sticky="w", pady=2)

        def _ok() -> None:
            result[0] = method_var.get()
            root.destroy()

        def _cancel() -> None:
            root.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        btn_frame.columnconfigure(0, weight=1)
        ttk.Button(btn_frame, text="Cancel", command=_cancel).grid(
            row=0, column=0, sticky="e", padx=(0, 6)
        )
        ok_btn = ttk.Button(btn_frame, text="OK", command=_ok)
        ok_btn.grid(row=0, column=1, sticky="e")

        root.protocol("WM_DELETE_WINDOW", _cancel)
        root.mainloop()
    except Exception:
        logger.exception("tkinter method-prompt failed")
        _destroy(root)
        return None

    return result[0]


def _prompt_method_stdin() -> int | None:
    """Prompt for registration method on stdin. Returns 1, 2, or None."""
    print("Deep Analysis — Register your agent:")
    print("  [1] Log in with email/password")
    print("  [2] Enter a registration code")
    try:
        choice = input("Select (or blank to cancel): ").strip()
    except EOFError:
        return None
    if choice == "1":
        return 1
    if choice == "2":
        return 2
    return None


def _prompt_method() -> int | None:
    tk_result = _prompt_method_tk()
    if isinstance(tk_result, _TkUnavailable):
        return _prompt_method_stdin()
    return tk_result


def _prompt_email_password_tk() -> tuple[str, str] | None | _TkUnavailable:
    """Two tkinter dialogs for email then password.

    Returns the pair, None if the user cancelled or left a field blank, or
    TK_UNAVAILABLE if tkinter could not be used.
    """
    root = _tk_root()
    if root is None:
        return TK_UNAVAILABLE

    try:
        from tkinter import simpledialog

        email = simpledialog.askstring(
            "Deep Analysis — Sign in",
            "Email:",
        )
        if email is None or not email.strip():
            return None
        email = email.strip()
        password = simpledialog.askstring(
            "Deep Analysis — Sign in",
            "Password:",
            show="*",
        )
    except Exception:
        logger.exception("tkinter credentials prompt failed")
        return None
    finally:
        _destroy(root)

    if not password:
        return None
    return email, password


def _prompt_email_password_stdin() -> tuple[str, str] | None:
    """Prompt for email + password on stdin. Uses getpass for the password."""
    import getpass

    print("Deep Analysis — sign in:")
    try:
        email = input("Email: ").strip()
    except EOFError:
        return None
    if not email:
        return None
    try:
        password = getpass.getpass("Password: ")
    except (EOFError, KeyboardInterrupt):
        return None
    if not password:
        return None
    return email, password


def _prompt_email_password() -> tuple[str, str] | None:
    tk_result = _prompt_email_password_tk()
    if isinstance(tk_result, _TkUnavailable):
        return _prompt_email_password_stdin()
    return tk_result


def _prompt_agent_name(default: str) -> str:
    """Prompt for an agent name; returns `default` if blank or cancelled."""
    root = _tk_root()
    if root is not None:
        try:
            from tkinter import simpledialog

            answer = simpledialog.askstring(
                "Deep Analysis — Agent name",
                f"Agent name (leave blank for default: {default}):",
            )
        except Exception:
            # The GUI is up, so do not drop to a console read here either.
            logger.exception("tkinter agent-name prompt failed")
            return default
        finally:
            _destroy(root)
        if answer is None:
            return default
        return answer.strip() or default

    try:
        entered = input(f"Agent name (default: {default}): ").strip()
    except EOFError:
        return default
    return entered or default


def _prompt_mtgo_dir_tk() -> str | None:
    """Ask the user to browse to their MTGO install. None if unavailable/cancelled."""
    root = _tk_root()
    if root is None:
        return None

    try:
        from tkinter import filedialog

        chosen = filedialog.askdirectory(
            title="Deep Analysis — Locate your MTGO install directory",
            mustexist=True,
        )
    except Exception:
        logger.exception("mtgo_dir_prompt_failed")
        return None
    finally:
        _destroy(root)

    if not chosen:
        return None
    return chosen


def _resolve_mtgo_log_dir(config: AppConfig) -> None:
    """Populate config.mtgo.log_dir. Tries default; falls back to a tkinter prompt.

    Never blocks registration — if everything fails, the default is kept
    (the watcher will log a clear error on startup so the user can fix it
    via the tray "Settings" option).
    """
    default_dir = _default_mtgo_log_dir()
    if default_dir.is_dir():
        config.mtgo.log_dir = default_dir
        logger.info("mtgo_log_dir_default_found", log_dir=str(default_dir))
        return

    chosen = _prompt_mtgo_dir_tk()
    if chosen and Path(chosen).is_dir():
        config.mtgo.log_dir = Path(chosen)
        logger.info("mtgo_log_dir_user_selected", log_dir=chosen)
        return

    config.mtgo.log_dir = default_dir
    logger.warning(
        "mtgo_log_dir_unresolved — default does not exist and user did not pick one",
        log_dir=str(default_dir),
    )


MAX_REGISTRATION_ATTEMPTS = 3


def _report_registration_failure(message: str, *, can_retry: bool) -> bool:
    """Tell the user registration failed. Returns True if they want to retry.

    The packaged tray app has no console, so a `print()` here is invisible:
    the user just sees the agent vanish. Report through a message box when
    one can be shown and only fall back to stdout when tkinter is genuinely
    unavailable. In that headless case `can_retry` is honoured as-is, which
    keeps the previous retry-until-attempts-exhausted behaviour.
    """
    root = _tk_root()
    if root is None:
        print(f"Registration failed: {message}")
        return can_retry

    try:
        from tkinter import messagebox

        if can_retry:
            retry = bool(
                messagebox.askretrycancel(
                    "Deep Analysis: registration failed",
                    f"{message}\n\nWould you like to try again?",
                )
            )
        else:
            messagebox.showerror(
                "Deep Analysis: registration failed",
                f"{message}\n\nNo attempts remaining. Start Deep Analysis again to try once more.",
            )
            retry = False
    except Exception:
        logger.exception("registration_failure_dialog_failed")
        print(f"Registration failed: {message}")
        return can_retry
    finally:
        _destroy(root)

    return retry


async def run_first_run_flow(config: AppConfig) -> bool:
    """Drive the interactive registration flow. Returns True on success."""
    if not config.agent.machine_name:
        config.agent.machine_name = _default_machine_name()

    method: int | None = None
    for _ in range(3):
        method = _prompt_method()
        if method in (1, 2):
            break
        if method is None:
            logger.info("first_run_cancelled")
            return False
    if method not in (1, 2):
        logger.error("first_run_no_method_selected")
        return False

    if method == 1:
        # Asked once, not once per attempt: the name does not depend on the
        # credentials, and re-asking after a bad password reads as a bug.
        agent_name: str | None = None
        for attempt in range(MAX_REGISTRATION_ATTEMPTS):
            creds = _prompt_email_password()
            if creds is None:
                logger.info("first_run_cancelled")
                return False
            email, password = creds
            if agent_name is None:
                agent_name = _prompt_agent_name(config.agent.machine_name)
            try:
                result = await auth.register_with_credentials(
                    config.server.url,
                    email=email,
                    password=password,
                    agent_name=agent_name,
                    client_version=__version__,
                    tls_verify=config.server.tls_verify,
                )
            except auth.RegistrationError as exc:
                logger.warning("first_run_register_with_credentials_failed", error=str(exc))
                can_retry = attempt < MAX_REGISTRATION_ATTEMPTS - 1
                if not _report_registration_failure(str(exc), can_retry=can_retry):
                    logger.error("first_run_gave_up", method="credentials")
                    return False
                continue

            config.agent.machine_name = agent_name
            config.agent.agent_id = result.agent_id
            config.agent.api_token = result.api_token
            config.agent.registered_at = datetime.now(UTC)
            _resolve_mtgo_log_dir(config)
            save_config(config)
            print(f"Registered! Agent ID: {result.agent_id}")
            logger.info(
                "first_run_registered",
                agent_id=result.agent_id,
                machine_name=config.agent.machine_name,
                method="credentials",
            )
            return True

        logger.error("first_run_gave_up", method="credentials")
        return False

    for attempt in range(MAX_REGISTRATION_ATTEMPTS):
        code = _prompt_code()
        if code is None:
            logger.info("first_run_cancelled")
            return False
        try:
            result = await auth.register(
                config.server.url,
                code=code,
                machine_name=config.agent.machine_name,
                client_version=__version__,
                tls_verify=config.server.tls_verify,
            )
        except auth.RegistrationError as exc:
            logger.warning("first_run_register_failed", error=str(exc))
            can_retry = attempt < MAX_REGISTRATION_ATTEMPTS - 1
            if not _report_registration_failure(str(exc), can_retry=can_retry):
                logger.error("first_run_gave_up", method="code")
                return False
            continue

        config.agent.agent_id = result.agent_id
        config.agent.api_token = result.api_token
        config.agent.registered_at = datetime.now(UTC)
        _resolve_mtgo_log_dir(config)
        save_config(config)
        logger.info(
            "first_run_registered",
            agent_id=result.agent_id,
            machine_name=config.agent.machine_name,
            method="code",
        )
        return True

    logger.error("first_run_gave_up", method="code")
    return False


def run_first_run_flow_sync(config: AppConfig) -> bool:
    """Sync wrapper for callers not already in an event loop."""
    return asyncio.run(run_first_run_flow(config))
