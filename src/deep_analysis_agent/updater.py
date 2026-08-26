"""Squirrel update checker: shells out to Update.exe (Clowd.Squirrel 2.x)."""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_UPDATE_URL = "https://github.com/sentania-labs/deep-analysis-agent/releases/latest/download"

_CHECK_TIMEOUT = 30


@dataclass(frozen=True)
class UpdateCheckResult:
    available: bool
    message: str


@dataclass(frozen=True)
class UpdateApplyResult:
    """Outcome of launching the Squirrel updater.

    ``started`` is the yes/no the caller usually wants, and truthiness
    follows it so ``if apply_update():`` still reads naturally. ``reason``
    and ``update_exe`` exist so a failure is diagnosable from the log,
    and ``detail`` is the sentence the tray shows the user.
    """

    started: bool
    reason: str
    detail: str
    update_exe: str | None = None

    def __bool__(self) -> bool:
        return self.started


def _find_update_exe() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    # Frozen exe lives in a versioned subdir; Update.exe is one level up.
    exe_dir = Path(sys.executable).resolve().parent
    candidate = exe_dir.parent / "Update.exe"
    return candidate if candidate.is_file() else None


def check_for_update(current_version: str) -> UpdateCheckResult:
    update_exe = _find_update_exe()
    if update_exe is None:
        return UpdateCheckResult(
            available=False,
            message="Update check unavailable (dev build).",
        )

    try:
        proc = subprocess.run(
            [str(update_exe), f"--checkForUpdate={_UPDATE_URL}"],
            capture_output=True,
            text=True,
            timeout=_CHECK_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("update_check_timeout")
        return UpdateCheckResult(available=False, message="Update check timed out.")
    except OSError:
        logger.exception("update_check_failed")
        return UpdateCheckResult(available=False, message="Update check failed.")

    stdout = proc.stdout.strip()
    logger.info(
        "update_check_result returncode=%d stdout=%s stderr=%s",
        proc.returncode,
        stdout,
        proc.stderr.strip(),
    )

    if proc.returncode != 0:
        logger.warning("update_check_nonzero returncode=%d", proc.returncode)
        return UpdateCheckResult(
            available=False,
            message=f"Update check failed (exit {proc.returncode}).",
        )

    if not stdout:
        return UpdateCheckResult(
            available=False,
            message=f"You're up to date (v{current_version}).",
        )

    return UpdateCheckResult(
        available=True,
        message="An update is available. It will install on next restart.",
    )


def apply_update() -> UpdateApplyResult:
    update_exe = _find_update_exe()
    if update_exe is None:
        logger.error("update_apply_failed reason=update_exe_missing update_exe=None")
        return UpdateApplyResult(
            started=False,
            reason="update_exe_missing",
            detail=(
                "The updater (Update.exe) was not found next to the app. "
                "Reinstall from the latest GitHub release."
            ),
        )
    try:
        subprocess.Popen(
            [str(update_exe), f"--update={_UPDATE_URL}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.exception(
            "update_apply_failed reason=launch_failed update_exe=%s error=%s",
            update_exe,
            exc,
        )
        return UpdateApplyResult(
            started=False,
            reason="launch_failed",
            detail=(
                "The updater would not launch. Use Open Log for the error, "
                "or install the latest GitHub release manually."
            ),
            update_exe=str(update_exe),
        )
    logger.info("update_apply_started update_exe=%s", update_exe)
    return UpdateApplyResult(
        started=True,
        reason="started",
        detail="The update will install on next restart.",
        update_exe=str(update_exe),
    )
