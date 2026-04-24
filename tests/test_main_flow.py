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
