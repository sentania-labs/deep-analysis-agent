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

import structlog

from . import auth
from .config import AppConfig, save_config

logger = structlog.get_logger(__name__)

CLIENT_VERSION = "0.4.0"


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


async def run_first_run_flow(config: AppConfig) -> bool:
    """Drive the interactive registration flow. Returns True on success."""
    if not config.agent.machine_name:
        config.agent.machine_name = _default_machine_name()

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
                client_version=CLIENT_VERSION,
                tls_verify=config.server.tls_verify,
            )
        except auth.RegistrationError as exc:
            logger.warning("first_run_register_failed", error=str(exc))
            print(f"Registration failed: {exc}")
            continue

        config.agent.agent_id = result.agent_id
        config.agent.api_token = result.api_token
        config.agent.registered_at = datetime.now(UTC)
        save_config(config)
        logger.info(
            "first_run_registered",
            agent_id=result.agent_id,
            machine_name=config.agent.machine_name,
        )
        return True

    logger.error("first_run_gave_up")
    return False


def run_first_run_flow_sync(config: AppConfig) -> bool:
    """Sync wrapper for callers not already in an event loop."""
    return asyncio.run(run_first_run_flow(config))
