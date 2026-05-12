"""Squirrel update checker — shells out to Update.exe (Clowd.Squirrel 2.x)."""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_UPDATE_URL = (
    "https://github.com/sentania-labs/deep-analysis-agent/releases/latest/download"
)

_CHECK_TIMEOUT = 30


@dataclass(frozen=True)
class UpdateCheckResult:
    available: bool
    message: str


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
            [str(update_exe), "check", "--url", _UPDATE_URL],
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

    if proc.returncode == 0 and not stdout:
        return UpdateCheckResult(
            available=False,
            message=f"You're up to date (v{current_version}).",
        )

    if stdout:
        return UpdateCheckResult(available=True, message=stdout)

    return UpdateCheckResult(
        available=True,
        message="An update is available — it will install on next restart.",
    )


def apply_update() -> bool:
    update_exe = _find_update_exe()
    if update_exe is None:
        return False
    try:
        subprocess.Popen(
            [str(update_exe), "download", "--url", _UPDATE_URL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        logger.exception("update_apply_failed")
        return False
