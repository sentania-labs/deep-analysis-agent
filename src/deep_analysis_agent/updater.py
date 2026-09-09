"""Squirrel update checker: shells out to Update.exe (Clowd.Squirrel 2.x)."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import SQUIRREL_APP_DIR_PREFIX, squirrel_update_exe

logger = logging.getLogger(__name__)

_UPDATE_URL = "https://github.com/sentania-labs/deep-analysis-agent/releases/latest/download"

_CHECK_TIMEOUT = 30
_APPLY_TIMEOUT = 120


@dataclass(frozen=True)
class UpdateCheckResult:
    available: bool
    message: str
    target_version: str | None = None


@dataclass(frozen=True)
class UpdateApplyResult:
    """Outcome of running the Squirrel updater.

    ``started`` remains the compatibility-facing success flag, but it is true
    only after the updater exits successfully. ``detail`` is safe to show in
    the tray for every outcome.
    """

    started: bool
    reason: str
    detail: str
    update_exe: str | None = None
    exit_code: int | None = None
    target_version: str | None = None

    def __bool__(self) -> bool:
        return self.started


def _find_update_exe() -> Path | None:
    """Compatibility alias for the shared Squirrel discovery helper."""
    return squirrel_update_exe()


def _parse_check_output(stdout: str) -> dict[str, Any] | None:
    """Return the final JSON object emitted after Squirrel progress lines."""
    for line in reversed(stdout.splitlines()):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _ready_app_versions(app_root: Path) -> dict[str, Path] | None:
    """Return complete Squirrel app directories keyed by their version."""
    try:
        children = list(app_root.iterdir())
    except OSError:
        logger.exception("update_app_directory_scan_failed app_root=%s", app_root)
        return None

    ready: dict[str, Path] = {}
    for child in children:
        if not child.is_dir() or not child.name.startswith(SQUIRREL_APP_DIR_PREFIX):
            continue
        version = child.name.removeprefix(SQUIRREL_APP_DIR_PREFIX)
        if version and not (child / ".not-finished").exists():
            ready[version] = child
    return ready


def _newest_ready_version(versions: dict[str, Path]) -> str | None:
    """Choose the most recently written ready app directory."""
    if not versions:
        return None

    def _write_time(item: tuple[str, Path]) -> tuple[int, str]:
        version, path = item
        try:
            return path.stat().st_mtime_ns, version
        except OSError:
            logger.exception("update_app_directory_stat_failed app_dir=%s", path)
            return 0, version

    return max(versions.items(), key=_write_time)[0]


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

    info = _parse_check_output(stdout)
    if info is None:
        logger.warning("update_check_invalid_output stdout=%s", stdout)
        return UpdateCheckResult(
            available=False,
            message="Update check returned an unexpected response. See Open Log.",
        )

    releases = info.get("releasesToApply")
    if not isinstance(releases, list):
        logger.warning("update_check_invalid_releases info=%s", info)
        return UpdateCheckResult(
            available=False,
            message="Update check returned an unexpected response. See Open Log.",
        )
    if not releases:
        installed_version = info.get("currentVersion")
        if (
            isinstance(installed_version, str)
            and installed_version.strip()
            and installed_version.strip() != current_version
        ):
            installed_version = installed_version.strip()
            return UpdateCheckResult(
                available=False,
                message=(
                    f"Update v{installed_version} is installed. Restart Deep Analysis to use it."
                ),
                target_version=installed_version,
            )
        return UpdateCheckResult(
            available=False,
            message=f"You're up to date (v{current_version}).",
        )

    target_version = info.get("futureVersion")
    if not isinstance(target_version, str) or not target_version.strip():
        logger.warning("update_check_missing_target_version info=%s", info)
        return UpdateCheckResult(
            available=False,
            message="Update check could not determine the target version. See Open Log.",
        )

    target_version = target_version.strip()
    return UpdateCheckResult(
        available=True,
        message=f"Update v{target_version} is available.",
        target_version=target_version,
    )


def apply_update(
    target_version: str | None = None,
) -> UpdateApplyResult:
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
            target_version=target_version,
        )
    ready_before = _ready_app_versions(update_exe.parent)
    try:
        proc = subprocess.Popen(
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
            target_version=target_version,
        )
    try:
        exit_code = proc.wait(timeout=_APPLY_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning(
            "update_apply_timeout update_exe=%s timeout_seconds=%s",
            update_exe,
            _APPLY_TIMEOUT,
        )
        return UpdateApplyResult(
            started=False,
            reason="timeout",
            detail=(
                f"Update timed out after {_APPLY_TIMEOUT:g} seconds and may still be running. "
                "See Open Log before restarting."
            ),
            update_exe=str(update_exe),
            target_version=target_version,
        )

    if exit_code != 0:
        logger.warning(
            "update_apply_nonzero update_exe=%s returncode=%d",
            update_exe,
            exit_code,
        )
        return UpdateApplyResult(
            started=False,
            reason="exit_nonzero",
            detail=f"Update failed (exit {exit_code}). See Open Log for details.",
            update_exe=str(update_exe),
            exit_code=exit_code,
            target_version=target_version,
        )

    installed_version = target_version
    if target_version is not None:
        ready_after = _ready_app_versions(update_exe.parent)
        if ready_before is None or ready_after is None:
            installed_version = None
        elif target_version not in ready_after:
            new_versions = {
                version: path
                for version, path in ready_after.items()
                if version not in ready_before
            }
            installed_version = _newest_ready_version(new_versions)
        if installed_version is None:
            logger.error(
                "update_apply_target_missing update_exe=%s target_version=%s ready_before=%s "
                "ready_after=%s",
                update_exe,
                target_version,
                sorted(ready_before) if ready_before is not None else None,
                sorted(ready_after) if ready_after is not None else None,
            )
            return UpdateApplyResult(
                started=False,
                reason="target_not_installed",
                detail=(
                    f"Update.exe exited successfully, but v{target_version} was not installed. "
                    "See Open Log for details."
                ),
                update_exe=str(update_exe),
                exit_code=0,
                target_version=target_version,
            )
        if installed_version != target_version:
            logger.info(
                "update_apply_feed_advanced expected_version=%s installed_version=%s",
                target_version,
                installed_version,
            )

    logger.info(
        "update_apply_completed update_exe=%s returncode=0 target_version=%s",
        update_exe,
        installed_version,
    )
    version_detail = f" v{installed_version}" if installed_version is not None else ""
    return UpdateApplyResult(
        started=True,
        reason="completed",
        detail=f"Update{version_detail} installed successfully. Restart Deep Analysis to use it.",
        update_exe=str(update_exe),
        exit_code=0,
        target_version=installed_version,
    )
