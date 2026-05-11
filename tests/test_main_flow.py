"""Integration-ish tests for the main file-handling coroutine.

No real network. shipper.ship_file is mocked via AsyncMock.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import structlog

from deep_analysis_agent import main as main_mod
from deep_analysis_agent import shipper
from deep_analysis_agent.config import AppConfig
from deep_analysis_agent.dedup import DedupStore


class _StubTray:
    def __init__(self) -> None:
        self.states: list[str] = []

    def set_state(self, s: str) -> None:
        self.states.append(s)


@pytest.fixture
def ctx(tmp_path: Path) -> tuple[AppConfig, DedupStore, _StubTray, Path]:
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTray()
    sample = tmp_path / "match.dat"
    sample.write_bytes(b"payload")
    return cfg, dedup, tray, sample


async def test_skip_if_seen(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, dedup, tray, sample = ctx
    sha = dedup.hash_file(sample)
    dedup.mark_seen(sha, sample)

    ship_mock = AsyncMock()
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), log)  # type: ignore[arg-type]
    ship_mock.assert_not_called()


async def test_mark_seen_after_ship(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, dedup, tray, sample = ctx

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), log)  # type: ignore[arg-type]

    sha = dedup.hash_file(sample)
    assert dedup.is_seen(sha) is True
    assert "uploading" in tray.states
    assert tray.states[-1] == "idle"


async def test_no_mark_on_ship_failure(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, dedup, tray, sample = ctx

    ship_mock = AsyncMock(side_effect=shipper.ShipError("kaboom"))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), log)  # type: ignore[arg-type]

    sha = dedup.hash_file(sample)
    assert dedup.is_seen(sha) is False
    assert tray.states[-1] == "error"


async def test_permission_error_retries_then_succeeds(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PermissionError on first hash attempt retries and succeeds on second."""
    cfg, dedup, tray, sample = ctx

    real_hash = dedup.hash_file(sample)
    call_count = 0

    def _hash_side_effect(path: Path) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise PermissionError("locked")
        return real_hash

    monkeypatch.setattr(dedup, "hash_file", _hash_side_effect)
    monkeypatch.setattr(main_mod, "_HASH_RETRY_DELAY", 0.0)

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f2"))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), log)  # type: ignore[arg-type]

    assert call_count == 2
    ship_mock.assert_called_once()
    assert tray.states[-1] == "idle"


async def test_permission_error_exhausts_retries(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PermissionError on every attempt gives up after _HASH_RETRIES attempts."""
    cfg, dedup, tray, sample = ctx

    call_count = 0

    def _always_locked(path: Path) -> str:
        nonlocal call_count
        call_count += 1
        raise PermissionError("locked")

    monkeypatch.setattr(dedup, "hash_file", _always_locked)
    monkeypatch.setattr(main_mod, "_HASH_RETRIES", 3)
    monkeypatch.setattr(main_mod, "_HASH_RETRY_DELAY", 0.0)

    ship_mock = AsyncMock()
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), log)  # type: ignore[arg-type]

    assert call_count == 3
    ship_mock.assert_not_called()


async def test_non_permission_oserror_no_retry(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-PermissionError OSError fails immediately without retrying."""
    cfg, dedup, tray, sample = ctx

    call_count = 0

    def _io_error(path: Path) -> str:
        nonlocal call_count
        call_count += 1
        raise OSError("disk failure")

    monkeypatch.setattr(dedup, "hash_file", _io_error)
    monkeypatch.setattr(main_mod, "_HASH_RETRY_DELAY", 0.0)

    ship_mock = AsyncMock()
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), log)  # type: ignore[arg-type]

    assert call_count == 1
    ship_mock.assert_not_called()
