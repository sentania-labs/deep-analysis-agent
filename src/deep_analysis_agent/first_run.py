"""First-run registration flow.

Prompts the user for a registration code (via tkinter if available,
falling back to stdin), exchanges it with the server, saves the
resulting `api_token` (DPAPI-wrapped) and `agent_id` to the config
TOML, and returns True on success.

Returns False if the user cancels, or if registration fails after the
user explicitly gives up. The caller (main) exits cleanly on False.
"""

from __future__ import annotations

import asyncio
import platform
import socket
from datetime import UTC, datetime
from pathlib import Path

import structlog

from . import __version__, auth
from .config import AppConfig, _default_mtgo_log_dir, save_config

logger = structlog.get_logger(__name__)


def _default_machine_name() -> str:
    try:
        return socket.gethostname() or platform.node() or "unknown"
    except Exception:
        return "unknown"


def _prompt_code_tk() -> str | None:
    """Show a tkinter dialog asking for the registration code.

    Returns the entered code stripped of whitespace, or None if the
    user cancelled. Returns the sentinel `""` (empty) if tkinter is
    unavailable — the caller falls back to stdin.
    """
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except ImportError:
        return ""

    try:
        root = tk.Tk()
        root.withdraw()
        code = simpledialog.askstring(
            "Deep Analysis — Register",
            "Paste your registration code (XXXX-XXXX):",
        )
        root.destroy()
    except Exception:
        logger.exception("tkinter dialog failed")
        return ""

    if code is None:
        return None
    return code.strip()


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
    if tk_result == "":
        return _prompt_code_stdin()
    return tk_result


def _prompt_method_tk() -> int | None:
    """Ask the user which registration method to use via tkinter.

    Returns 1 for email/password, 2 for registration code, None if the
    user cancelled. Returns -1 if tkinter is unavailable.
    """
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except ImportError:
        return -1

    try:
        root = tk.Tk()
        root.withdraw()
        for _ in range(2):
            answer = simpledialog.askstring(
                "Deep Analysis — Register",
                "Enter 1 for Email/Password or 2 for Registration Code:",
            )
            if answer is None:
                root.destroy()
                return None
            answer = answer.strip()
            if answer == "1":
                root.destroy()
                return 1
            if answer == "2":
                root.destroy()
                return 2
        root.destroy()
        return None
    except Exception:
        logger.exception("tkinter method-prompt failed")
        return -1


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
    if tk_result == -1:
        return _prompt_method_stdin()
    return tk_result


def _prompt_email_password_tk() -> tuple[str, str] | None:
    """Two tkinter dialogs for email then password. None if unavailable/cancelled."""
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except ImportError:
        return None

    try:
        root = tk.Tk()
        root.withdraw()
        email = simpledialog.askstring(
            "Deep Analysis — Sign in",
            "Email:",
        )
        if email is None:
            root.destroy()
            return None
        email = email.strip()
        if not email:
            root.destroy()
            return None
        password = simpledialog.askstring(
            "Deep Analysis — Sign in",
            "Password:",
            show="*",
        )
        root.destroy()
    except Exception:
        logger.exception("tkinter credentials prompt failed")
        return None

    if password is None or not password:
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
    if tk_result is not None:
        return tk_result
    return _prompt_email_password_stdin()


def _prompt_agent_name(default: str) -> str:
    """Prompt for an agent name; returns `default` if blank or cancelled."""
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except ImportError:
        tk = None  # type: ignore[assignment]
        simpledialog = None  # type: ignore[assignment]

    if tk is not None and simpledialog is not None:
        try:
            root = tk.Tk()
            root.withdraw()
            answer = simpledialog.askstring(
                "Deep Analysis — Agent name",
                f"Agent name (leave blank for default: {default}):",
            )
            root.destroy()
            if answer is None:
                return default
            answer = answer.strip()
            return answer or default
        except Exception:
            logger.exception("tkinter agent-name prompt failed")

    try:
        entered = input(f"Agent name (default: {default}): ").strip()
    except EOFError:
        return default
    return entered or default


def _prompt_mtgo_dir_tk() -> str | None:
    """Ask the user to browse to their MTGO install. None if unavailable/cancelled."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    try:
        root = tk.Tk()
        root.withdraw()
        chosen = filedialog.askdirectory(
            title="Deep Analysis — Locate your MTGO install directory",
            mustexist=True,
        )
        root.destroy()
    except Exception:
        logger.exception("mtgo_dir_prompt_failed")
        return None

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
        creds = _prompt_email_password()
        if creds is None:
            logger.info("first_run_cancelled")
            return False
        email, password = creds
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
            print(f"Registration failed: {exc}")
            return False

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

    for _attempt in range(3):
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
            print(f"Registration failed: {exc}")
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

    logger.error("first_run_gave_up")
    return False


def run_first_run_flow_sync(config: AppConfig) -> bool:
    """Sync wrapper for callers not already in an event loop."""
    return asyncio.run(run_first_run_flow(config))
