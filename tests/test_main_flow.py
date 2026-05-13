"""Integration-ish tests for the main file-handling coroutine.

No real network. shipper.ship_file is mocked via AsyncMock.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from deep_analysis_agent import auth, shipper
from deep_analysis_agent import main as main_mod
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


# --- _parse_version ---


def test_parse_version_simple() -> None:
    assert main_mod._parse_version("0.4.8") == (0, 4, 8)


def test_parse_version_two_part() -> None:
    assert main_mod._parse_version("1.0") == (1, 0)


def test_parse_version_single() -> None:
    assert main_mod._parse_version("3") == (3,)


def test_parse_version_stops_at_non_numeric() -> None:
    assert main_mod._parse_version("1.2.3rc1") == (1, 2)


def test_parse_version_comparison() -> None:
    assert main_mod._parse_version("0.4.8") < main_mod._parse_version("0.5.0")
    assert main_mod._parse_version("0.5.0") == main_mod._parse_version("0.5.0")
    assert main_mod._parse_version("1.0.0") > main_mod._parse_version("0.99.99")


# --- _heartbeat_loop: version floor check ---


class _StubTrayWithNotify:
    """Tray stub that also tracks notify calls."""

    def __init__(self) -> None:
        self.states: list[str] = []
        self._paused = False
        self._icon = MagicMock()

    def set_state(self, s: str) -> None:
        self.states.append(s)


async def test_heartbeat_version_below_minimum_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When server requires a higher version, tray goes to error and notify fires."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.agent.heartbeat_interval_seconds = 30
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTrayWithNotify()
    log = structlog.get_logger("test")
    stop = asyncio.Event()
    revoked = asyncio.Event()
    watcher_box: list[None] = [None]

    call_count = 0

    async def _fake_heartbeat(*_a: object, **_kw: object) -> auth.HeartbeatResult:
        nonlocal call_count
        call_count += 1
        # Stop after first iteration to avoid infinite loop.
        stop.set()
        return auth.HeartbeatResult(
            status="ok",
            registered_at=None,
            revoked=False,
            upload_count=0,
            min_agent_version="99.0.0",
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        lambda: None,
        stop,
        revoked,
        log,  # type: ignore[arg-type]
    )
    assert "error" in tray.states
    tray._icon.notify.assert_called_once()
    msg = tray._icon.notify.call_args[0][0]
    assert "99.0.0" in msg


async def test_heartbeat_version_ok_no_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When agent meets the minimum version, no error state is set."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.agent.heartbeat_interval_seconds = 30
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTrayWithNotify()
    log = structlog.get_logger("test")
    stop = asyncio.Event()
    revoked = asyncio.Event()
    watcher_box: list[None] = [None]

    async def _fake_heartbeat(*_a: object, **_kw: object) -> auth.HeartbeatResult:
        stop.set()
        return auth.HeartbeatResult(
            status="ok",
            registered_at=None,
            revoked=False,
            upload_count=0,
            min_agent_version="0.1.0",
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        lambda: None,
        stop,
        revoked,
        log,  # type: ignore[arg-type]
    )
    assert "error" not in tray.states
    tray._icon.notify.assert_not_called()


async def test_heartbeat_version_warn_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The version warning fires only once per session, not every heartbeat."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.agent.heartbeat_interval_seconds = 30
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTrayWithNotify()
    log = structlog.get_logger("test")
    stop = asyncio.Event()
    revoked = asyncio.Event()
    watcher_box: list[None] = [None]

    call_count = 0

    async def _fake_heartbeat(*_a: object, **_kw: object) -> auth.HeartbeatResult:
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            stop.set()
        return auth.HeartbeatResult(
            status="ok",
            registered_at=None,
            revoked=False,
            upload_count=0,
            min_agent_version="99.0.0",
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        lambda: None,
        stop,
        revoked,
        log,  # type: ignore[arg-type]
    )
    # notify should have been called exactly once despite multiple heartbeats.
    assert tray._icon.notify.call_count == 1


# --- _heartbeat_loop: resync sets tray to uploading ---


async def test_resync_sets_tray_uploading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After a resync triggers a watcher restart, the tray shows uploading."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.agent.heartbeat_interval_seconds = 30
    dedup = DedupStore(tmp_path / "dedup.db")
    # Seed the dedup store with some entries so local_count > 0.
    for i in range(10):
        dedup.mark_seen(f"sha{i:04d}", tmp_path / f"file{i}.dat")

    tray = _StubTrayWithNotify()
    log = structlog.get_logger("test")
    stop = asyncio.Event()
    revoked = asyncio.Event()

    watcher_started = False

    class _FakeWatcher:
        def start(self) -> None:
            nonlocal watcher_started
            watcher_started = True

        def stop(self) -> None:
            pass

    watcher_box: list[_FakeWatcher | None] = [_FakeWatcher()]

    async def _fake_heartbeat(*_a: object, **_kw: object) -> auth.HeartbeatResult:
        stop.set()
        return auth.HeartbeatResult(
            status="ok",
            registered_at=None,
            revoked=False,
            upload_count=0,  # server says 0, local has 10 => triggers resync
            min_agent_version=None,
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        _FakeWatcher,
        stop,
        revoked,
        log,  # type: ignore[arg-type]
    )
    assert "uploading" in tray.states
    assert watcher_started
