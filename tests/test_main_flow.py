"""Integration-ish tests for the main file-handling coroutine.

No real network. shipper.ship_file is mocked via AsyncMock.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
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
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]
    ship_mock.assert_not_called()


async def test_mark_seen_after_ship(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, dedup, tray, sample = ctx

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1000))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

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
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1001))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

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
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

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
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

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


async def test_heartbeat_version_below_minimum_blocks_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When server requires a higher version, uploads are blocked and user is notified."""
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
            reingest_requested_at=None,
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    version_blocked = asyncio.Event()
    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        lambda: None,
        stop,
        revoked,
        version_blocked,
        [],
        log,  # type: ignore[arg-type]
    )
    assert "error" in tray.states
    assert version_blocked.is_set(), "version_blocked event should be set"
    tray._icon.notify.assert_called_once()
    msg = tray._icon.notify.call_args[0][0]
    assert "99.0.0" in msg
    assert "Upload paused" in msg
    assert "Please update" in msg


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
            reingest_requested_at=None,
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    version_blocked = asyncio.Event()
    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        lambda: None,
        stop,
        revoked,
        version_blocked,
        [],
        log,  # type: ignore[arg-type]
    )
    assert "error" not in tray.states
    assert not version_blocked.is_set(), "version_blocked should not be set"
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
            reingest_requested_at=None,
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    version_blocked = asyncio.Event()
    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        lambda: None,
        stop,
        revoked,
        version_blocked,
        [],
        log,  # type: ignore[arg-type]
    )
    # notify should have been called exactly once despite multiple heartbeats.
    assert tray._icon.notify.call_count == 1
    assert version_blocked.is_set(), "version_blocked should remain set"


# --- version lockout: _handle_file skips when blocked ---


async def test_handle_file_defers_when_version_blocked(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When version_blocked is set, _handle_file defers the path instead of dropping it."""
    cfg, dedup, tray, sample = ctx

    ship_mock = AsyncMock()
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    version_blocked = asyncio.Event()
    version_blocked.set()  # simulate version lockout
    deferred: list[Path] = []

    log = structlog.get_logger("test")
    await main_mod._handle_file(
        sample,
        cfg,
        dedup,
        tray,
        asyncio.Event(),
        version_blocked,
        deferred,
        log,
    )  # type: ignore[arg-type]

    ship_mock.assert_not_called()
    assert sample in deferred, "blocked file should be added to deferred list"


async def test_handle_file_proceeds_when_version_not_blocked(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When version_blocked is NOT set, _handle_file uploads normally."""
    cfg, dedup, tray, sample = ctx

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1000))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    version_blocked = asyncio.Event()  # not set

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), version_blocked, [], log)  # type: ignore[arg-type]

    ship_mock.assert_called_once()
    assert tray.states[-1] == "idle"


async def test_version_block_cleared_after_update_drains_deferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After version goes from blocked to acceptable, deferred files are drained.

    We run two heartbeat-loop passes sharing the same version_blocked event
    and deferred_paths list:
    pass 1 blocks (version too old), then _handle_file defers the file;
    pass 2 unblocks (requirement lowered) and the heartbeat loop drains
    deferred_paths automatically.
    """
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.agent.heartbeat_interval_seconds = 30
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTrayWithNotify()
    log = structlog.get_logger("test")
    watcher_box: list[None] = [None]
    version_blocked = asyncio.Event()
    deferred: list[Path] = []

    # --- Pass 1: version too old → block uploads ---
    stop1 = asyncio.Event()
    revoked1 = asyncio.Event()

    async def _hb_blocked(*_a: object, **_kw: object) -> auth.HeartbeatResult:
        stop1.set()
        return auth.HeartbeatResult(
            status="ok",
            registered_at=None,
            revoked=False,
            upload_count=0,
            min_agent_version="99.0.0",
        )

    monkeypatch.setattr(auth, "heartbeat", _hb_blocked)

    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        lambda: None,
        stop1,
        revoked1,
        version_blocked,
        deferred,
        log,  # type: ignore[arg-type]
    )
    assert version_blocked.is_set(), "should be blocked after first pass"

    # File arrives while blocked — should be deferred, not dropped.
    sample = tmp_path / "match.dat"
    sample.write_bytes(b"payload")
    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1000))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)
    await main_mod._handle_file(
        sample,
        cfg,
        dedup,
        tray,
        asyncio.Event(),
        version_blocked,
        deferred,
        log,
    )  # type: ignore[arg-type]
    ship_mock.assert_not_called()
    assert sample in deferred, "file should be in the deferred list"

    # --- Pass 2: version now acceptable → unblock + drain ---
    stop2 = asyncio.Event()
    revoked2 = asyncio.Event()

    async def _hb_ok(*_a: object, **_kw: object) -> auth.HeartbeatResult:
        stop2.set()
        return auth.HeartbeatResult(
            status="ok",
            registered_at=None,
            revoked=False,
            upload_count=0,
            min_agent_version="0.0.1",
        )

    monkeypatch.setattr(auth, "heartbeat", _hb_ok)

    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        lambda: None,
        stop2,
        revoked2,
        version_blocked,
        deferred,
        log,  # type: ignore[arg-type]
    )
    assert not version_blocked.is_set(), "should be unblocked after second pass"

    # The heartbeat loop should have drained the deferred file automatically.
    ship_mock.assert_called_once()
    assert len(deferred) == 0, "deferred list should be empty after drain"


async def test_deferred_files_processed_in_order_after_unblock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple files deferred during a version block are drained in FIFO order."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.agent.heartbeat_interval_seconds = 30
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTrayWithNotify()
    log = structlog.get_logger("test")
    watcher_box: list[None] = [None]
    version_blocked = asyncio.Event()
    deferred: list[Path] = []

    # Block uploads.
    version_blocked.set()

    # Simulate three files arriving while blocked.
    shipped_order: list[str] = []
    files = []
    for i in range(3):
        f = tmp_path / f"Match_GameLog_{i:05d}.dat"
        f.write_bytes(f"payload-{i}".encode())
        files.append(f)
        await main_mod._handle_file(
            f,
            cfg,
            dedup,
            tray,
            asyncio.Event(),
            version_blocked,
            deferred,
            log,
        )  # type: ignore[arg-type]

    assert len(deferred) == 3

    # Track ship order.
    async def _ship_tracking(*args: object, **kwargs: object) -> shipper.UploadResult:
        path_arg = args[2]  # positional: url, token, path
        shipped_order.append(path_arg.name)
        return shipper.UploadResult(deduped=False, upload_id=1002)

    monkeypatch.setattr(shipper, "ship_file", _ship_tracking)

    # Unblock via heartbeat.
    stop = asyncio.Event()

    async def _hb_ok(*_a: object, **_kw: object) -> auth.HeartbeatResult:
        stop.set()
        return auth.HeartbeatResult(
            status="ok",
            registered_at=None,
            revoked=False,
            upload_count=0,
            min_agent_version="0.0.1",
        )

    monkeypatch.setattr(auth, "heartbeat", _hb_ok)

    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        lambda: None,
        stop,
        asyncio.Event(),
        version_blocked,
        deferred,
        log,  # type: ignore[arg-type]
    )

    assert len(deferred) == 0, "all deferred files should be drained"
    assert len(shipped_order) == 3, "all three files should have been shipped"
    assert shipped_order == [f.name for f in files], "files should be shipped in FIFO order"


# --- _heartbeat_loop: resync sets tray to uploading ---


# --- detect_content_type ---


def test_detect_content_type_match_log() -> None:
    assert main_mod.detect_content_type("Match_GameLog_12345.dat") == "match-log"


def test_detect_content_type_decklist() -> None:
    assert main_mod.detect_content_type("grouping 98765.xml") == "decklist"


def test_detect_content_type_unknown() -> None:
    assert main_mod.detect_content_type("random_file.txt") == "unknown"


def test_detect_content_type_decklist_various_ids() -> None:
    assert main_mod.detect_content_type("grouping 1.xml") == "decklist"
    assert main_mod.detect_content_type("grouping 999999999.xml") == "decklist"


def test_detect_content_type_not_grouping_without_space() -> None:
    """'grouping' without a space and ID should not match the decklist pattern."""
    assert main_mod.detect_content_type("grouping.xml") == "unknown"


# --- _handle_file passes content_type and original_filename ---


async def test_handle_file_passes_content_type_decklist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When handling a grouping XML file, ship_file receives content_type=decklist."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTray()
    sample = tmp_path / "grouping 12345.xml"
    sample.write_bytes(b"<grouping>deck</grouping>")

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1000))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

    ship_mock.assert_called_once()
    call_kwargs = ship_mock.call_args
    assert call_kwargs.kwargs["content_type"] == "decklist"
    assert call_kwargs.kwargs["original_filename"] == "grouping 12345.xml"


async def test_handle_file_passes_content_type_match_log(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When handling a .dat match log, ship_file receives content_type=match-log."""
    cfg, dedup, tray, sample = ctx

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1001))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

    ship_mock.assert_called_once()
    call_kwargs = ship_mock.call_args
    # sample is "match.dat" which does NOT match "Match_GameLog_*.dat", so it's "unknown"
    assert call_kwargs.kwargs["content_type"] == "unknown"
    assert call_kwargs.kwargs["original_filename"] == "match.dat"


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
            reingest_requested_at=None,
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    version_blocked = asyncio.Event()
    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        _FakeWatcher,
        stop,
        revoked,
        version_blocked,
        [],
        log,  # type: ignore[arg-type]
    )
    assert "uploading" in tray.states
    assert watcher_started


# --- Mtime-aware decklist dedup ---


async def test_decklist_same_hash_different_mtime_reshipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decklist file with the same hash but different mtime should be re-shipped."""
    import os

    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTray()
    sample = tmp_path / "grouping 12345.xml"
    sample.write_bytes(b"<grouping>deck v1</grouping>")

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1000))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")

    # First ship — registers the file in dedup.
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]
    assert ship_mock.call_count == 1
    ship_mock.reset_mock()

    # Simulate round-trip edit: user changes deck, plays, reverts to same content.
    # Content (and thus hash) is identical, but mtime changed.
    os.utime(sample, (sample.stat().st_atime, sample.stat().st_mtime + 60))

    # The is_path_unchanged check should see the mtime difference.
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]
    assert ship_mock.call_count == 1, "decklist with changed mtime should be re-shipped"

    # Verify file_mtime was passed.
    call_kwargs = ship_mock.call_args.kwargs
    assert call_kwargs.get("file_mtime") is not None


async def test_match_log_same_hash_still_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A match-log file with the same hash should still be skipped (hash-only dedup)."""
    import os

    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTray()
    sample = tmp_path / "Match_GameLog_99999.dat"
    sample.write_bytes(b"match log payload")

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1000))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")

    # First ship.
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]
    assert ship_mock.call_count == 1
    ship_mock.reset_mock()

    # Touch the file to change mtime, but keep same content.
    os.utime(sample, (sample.stat().st_atime, sample.stat().st_mtime + 60))

    # Match log should still be skipped because hash is the same.
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]
    assert ship_mock.call_count == 0, "match-log with same hash should be skipped"


async def test_decklist_same_hash_same_mtime_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decklist with same hash AND same mtime should be skipped (no change)."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTray()
    sample = tmp_path / "grouping 77777.xml"
    sample.write_bytes(b"<grouping>stable deck</grouping>")

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1000))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")

    # First ship.
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]
    assert ship_mock.call_count == 1
    ship_mock.reset_mock()

    # Same file, no mtime change — should be skipped.
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]
    assert ship_mock.call_count == 0, "unchanged decklist should be skipped"


async def test_decklist_ship_includes_file_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When shipping a decklist, file_mtime is passed to ship_file."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTray()
    sample = tmp_path / "grouping 55555.xml"
    sample.write_bytes(b"<grouping>deck data</grouping>")

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1000))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

    ship_mock.assert_called_once()
    call_kwargs = ship_mock.call_args.kwargs
    assert call_kwargs["file_mtime"] == pytest.approx(sample.stat().st_mtime, abs=1.0)


async def test_match_log_inconclusive_still_ships(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A match log without a finalized signal still ships, tagged inconclusive."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTray()
    sample = tmp_path / "Match_GameLog_inflight.dat"
    sample.write_bytes(b"opening hands\nturn 1\nturn 2\n")

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1003))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

    ship_mock.assert_called_once()
    kwargs = ship_mock.call_args.kwargs
    assert kwargs["agent_classification"] == "inconclusive"


async def test_match_log_complete_classification_passed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A match log with a finalized signal ships as complete."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTray()
    sample = tmp_path / "Match_GameLog_done.dat"
    sample.write_bytes(b"...turn 12...\nAlice wins the match\n")

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1004))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

    ship_mock.assert_called_once()
    kwargs = ship_mock.call_args.kwargs
    assert kwargs["agent_classification"] == "complete"


async def test_decklist_no_agent_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decklists are not match logs and should not carry an agent_classification."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTray()
    sample = tmp_path / "grouping 31337.xml"
    sample.write_bytes(b"<grouping>deck</grouping>")

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1005))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

    ship_mock.assert_called_once()
    kwargs = ship_mock.call_args.kwargs
    assert kwargs["agent_classification"] is None


async def test_match_log_proper_name_no_file_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Match log ships should not include file_mtime."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTray()
    sample = tmp_path / "Match_GameLog_12345.dat"
    sample.write_bytes(b"match log data")

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, upload_id=1000))
    monkeypatch.setattr(shipper, "ship_file", ship_mock)

    log = structlog.get_logger("test")
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]

    ship_mock.assert_called_once()
    call_kwargs = ship_mock.call_args.kwargs
    assert call_kwargs.get("file_mtime") is None


# --- _heartbeat_loop: reingest signal ---


async def test_reingest_signal_triggers_clear_and_watcher_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When server sends a reingest timestamp, agent clears seen-files and restarts watcher."""
    from datetime import UTC, datetime

    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.agent.heartbeat_interval_seconds = 30
    dedup = DedupStore(tmp_path / "dedup.db")
    # Seed the dedup store with files.
    for i in range(5):
        dedup.mark_seen(f"sha{i:04d}", tmp_path / f"file{i}.dat")
    assert dedup.count() == 5

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
    reingest_ts = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)

    async def _fake_heartbeat(*_a: object, **_kw: object) -> auth.HeartbeatResult:
        stop.set()
        return auth.HeartbeatResult(
            status="ok",
            registered_at=None,
            revoked=False,
            upload_count=5,
            min_agent_version=None,
            reingest_requested_at=reingest_ts,
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    version_blocked = asyncio.Event()
    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        _FakeWatcher,
        stop,
        revoked,
        version_blocked,
        [],
        log,  # type: ignore[arg-type]
    )
    # Seen-files should be cleared.
    assert dedup.count() == 0
    # Meta should be preserved with the reingest timestamp (UTC-normalized).
    assert dedup.get_meta("last_reingest_at") == reingest_ts.isoformat()
    # Watcher should have been restarted.
    assert watcher_started
    assert "uploading" in tray.states


async def test_reingest_same_timestamp_does_not_retrigger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the server sends the same reingest timestamp, agent does NOT re-trigger."""
    from datetime import UTC, datetime

    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.agent.heartbeat_interval_seconds = 30
    dedup = DedupStore(tmp_path / "dedup.db")

    reingest_ts = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
    # Pre-set the meta as if we already handled this timestamp.
    dedup.set_meta("last_reingest_at", reingest_ts.isoformat())
    # Seed some files that should NOT be cleared.
    for i in range(3):
        dedup.mark_seen(f"sha{i:04d}", tmp_path / f"file{i}.dat")
    assert dedup.count() == 3

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
            upload_count=3,
            min_agent_version=None,
            reingest_requested_at=reingest_ts,
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    version_blocked = asyncio.Event()
    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        _FakeWatcher,
        stop,
        revoked,
        version_blocked,
        [],
        log,  # type: ignore[arg-type]
    )
    # Files should NOT have been cleared — same timestamp.
    assert dedup.count() == 3
    assert not watcher_started


async def test_reingest_newer_timestamp_retriggers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A newer reingest timestamp triggers another clear + watcher restart."""
    from datetime import UTC, datetime

    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.agent.heartbeat_interval_seconds = 30
    dedup = DedupStore(tmp_path / "dedup.db")

    old_ts = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
    new_ts = datetime(2026, 5, 26, 14, 0, 0, tzinfo=UTC)
    # Pre-set the meta with the older timestamp.
    dedup.set_meta("last_reingest_at", old_ts.isoformat())
    # Seed files that should be cleared on the newer reingest.
    for i in range(4):
        dedup.mark_seen(f"sha{i:04d}", tmp_path / f"file{i}.dat")
    assert dedup.count() == 4

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
            upload_count=4,
            min_agent_version=None,
            reingest_requested_at=new_ts,
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    version_blocked = asyncio.Event()
    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        _FakeWatcher,
        stop,
        revoked,
        version_blocked,
        [],
        log,  # type: ignore[arg-type]
    )
    # Files should be cleared because the newer timestamp is greater.
    assert dedup.count() == 0
    assert dedup.get_meta("last_reingest_at") == new_ts.isoformat()
    assert watcher_started
    assert "uploading" in tray.states


async def test_reingest_no_signal_does_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When reingest_requested_at is None, no reingest action is taken."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.agent.heartbeat_interval_seconds = 30
    dedup = DedupStore(tmp_path / "dedup.db")
    for i in range(3):
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
            upload_count=3,
            min_agent_version=None,
            reingest_requested_at=None,
        )

    monkeypatch.setattr(auth, "heartbeat", _fake_heartbeat)

    version_blocked = asyncio.Event()
    await main_mod._heartbeat_loop(
        cfg,
        tray,
        dedup,
        watcher_box,
        _FakeWatcher,
        stop,
        revoked,
        version_blocked,
        [],
        log,  # type: ignore[arg-type]
    )
    # Nothing should have changed.
    assert dedup.count() == 3
    assert dedup.get_meta("last_reingest_at") is None
    assert not watcher_started


# --- _schedule_tray_notification: race when _icon is None ---


def test_schedule_tray_notification_no_raise_when_icon_is_none() -> None:
    """_schedule_tray_notification must not raise when tray._icon is None."""

    class _TrayWithNullIcon:
        _icon: object = None

    tray = _TrayWithNullIcon()
    # Use delay=0 so the thread finishes quickly.
    main_mod._schedule_tray_notification(tray, "hello", delay=0)  # type: ignore[arg-type]
    # Give the daemon thread time to run and (potentially) blow up.
    import time

    time.sleep(0.1)
    # If we get here without an unhandled exception the guard works.


def test_schedule_tray_notification_calls_notify_when_icon_present() -> None:
    """When _icon is set, the notification is forwarded."""

    notified: list[tuple[str, str]] = []

    class _FakeIcon:
        def notify(self, message: str, title: str) -> None:
            notified.append((message, title))

    class _TrayWithIcon:
        _icon = _FakeIcon()

    tray = _TrayWithIcon()
    main_mod._schedule_tray_notification(tray, "test msg", title="Test", delay=0)  # type: ignore[arg-type]
    import time

    time.sleep(0.2)
    assert len(notified) == 1
    assert notified[0] == ("test msg", "Test")


# --- Upload queue worker: slow uploads are not failures (issue #39) ---


class _RecordingLog:
    """Minimal structlog-shaped logger that records what was emitted."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def _record(self, level: str, event: str, **_kw: object) -> None:
        self.events.append((level, event))

    def info(self, event: str, **kw: object) -> None:
        self._record("info", event, **kw)

    def debug(self, event: str, **kw: object) -> None:
        self._record("debug", event, **kw)

    def warning(self, event: str, **kw: object) -> None:
        self._record("warning", event, **kw)

    def error(self, event: str, **kw: object) -> None:
        self._record("error", event, **kw)

    def exception(self, event: str, **kw: object) -> None:
        self._record("exception", event, **kw)

    def names(self) -> list[str]:
        return [e for _, e in self.events]


async def test_slow_upload_is_not_reported_as_failure() -> None:
    """A slow _handle_file must never be logged as a failure while it runs."""
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    release = asyncio.Event()
    finished: list[Path] = []

    async def handle(path: Path) -> None:
        await release.wait()
        finished.append(path)

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log)  # type: ignore[arg-type]
    )
    q.put_nowait(Path("slow.dat"))

    # Let the worker pick the file up and sit on the slow handler.
    for _ in range(20):
        await asyncio.sleep(0.01)
    assert not finished, "handler should still be in flight"
    assert "handle_file_raised" not in log.names()
    assert "error" not in tray.states

    release.set()
    await asyncio.wait_for(q.join(), timeout=5)
    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker

    assert finished == [Path("slow.dat")]
    assert "handle_file_raised" not in log.names()
    assert "error" not in tray.states


async def test_failed_upload_is_reported_and_worker_continues() -> None:
    """A genuine failure reaches the log and the tray, and does not kill the worker."""
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    handled: list[Path] = []

    async def handle(path: Path) -> None:
        handled.append(path)
        if path.name == "bad.dat":
            raise RuntimeError("boom")

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log)  # type: ignore[arg-type]
    )
    q.put_nowait(Path("bad.dat"))
    q.put_nowait(Path("good.dat"))
    await asyncio.wait_for(q.join(), timeout=5)
    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker

    assert "handle_file_raised" in log.names()
    assert tray.states == ["error"]
    # The failure did not stop the queue.
    assert handled == [Path("bad.dat"), Path("good.dat")]


async def test_slow_file_does_not_block_the_next_file() -> None:
    """Enqueueing from the watcher thread returns at once while an upload runs."""
    import time

    loop = asyncio.get_running_loop()
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    release = asyncio.Event()
    handled: list[Path] = []

    async def handle(path: Path) -> None:
        if path.name == "slow.dat":
            await release.wait()
        handled.append(path)

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log)  # type: ignore[arg-type]
    )
    on_file_ready = main_mod.make_enqueuer(loop, q, log)  # type: ignore[arg-type]

    elapsed: list[float] = []

    def watcher_thread() -> None:
        # Mirrors the watcher's single worker thread: two files back to back.
        for name in ("slow.dat", "next.dat"):
            start = time.monotonic()
            on_file_ready(Path(name))
            elapsed.append(time.monotonic() - start)

    t = threading.Thread(target=watcher_thread, name="fake-watcher")
    t.start()
    await asyncio.to_thread(t.join)
    # Let the queued call_soon_threadsafe callbacks land and the worker pick
    # up the first file.
    for _ in range(20):
        await asyncio.sleep(0.01)

    # The watcher thread got both files queued while the first is still uploading.
    assert len(elapsed) == 2
    assert max(elapsed) < 1.0
    assert not handled, "slow upload should still be in flight"
    assert q.qsize() == 1, "second file waits in the queue, not on the watcher thread"

    release.set()
    await asyncio.wait_for(q.join(), timeout=5)
    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker

    assert handled == [Path("slow.dat"), Path("next.dat")]
    assert "handle_file_raised" not in log.names()


def test_enqueue_on_closed_loop_is_logged_not_raised() -> None:
    """Enqueueing after the loop is gone warns instead of raising into the watcher."""
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()

    on_file_ready = main_mod.make_enqueuer(closed_loop, q, log)  # type: ignore[arg-type]
    on_file_ready(Path("late.dat"))

    assert "upload_enqueue_dropped_loop_closed" in log.names()


async def test_dead_upload_worker_is_reported() -> None:
    """A worker that dies must say so instead of silently stopping uploads."""
    log = _RecordingLog()
    tray = _StubTray()

    async def boom() -> None:
        raise BaseException("fatal")  # noqa: TRY002 — the case except Exception misses

    task: asyncio.Task[None] = asyncio.ensure_future(boom())  # type: ignore[arg-type]
    with contextlib.suppress(BaseException):
        await task
    main_mod.log_worker_exit(task, tray, log)  # type: ignore[arg-type]

    assert "upload_worker_died — uploads have stopped" in log.names()
    assert tray.states == ["error"]


async def test_worker_exit_callback_silent_on_cancel() -> None:
    """Normal shutdown cancellation is not reported as a worker death."""
    log = _RecordingLog()
    tray = _StubTray()
    q: asyncio.Queue[Path] = asyncio.Queue()

    async def handle(path: Path) -> None:  # pragma: no cover — never called
        return None

    task = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log)  # type: ignore[arg-type]
    )
    await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    main_mod.log_worker_exit(task, tray, log)  # type: ignore[arg-type]

    assert log.names() == []
    assert tray.states == []


# --- Pause Sync actually pauses the backlog (Codex P1 on PR #52) ---


async def _settle(ticks: int = 20) -> None:
    """Give the loop enough turns for the worker to act (or prove it did not)."""
    for _ in range(ticks):
        await asyncio.sleep(0.01)


async def test_pause_stops_draining_the_queued_backlog() -> None:
    """Pausing mid-upload lets the in-flight file finish and ships nothing else."""
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    resume = asyncio.Event()
    resume.set()
    release = asyncio.Event()
    handled: list[Path] = []

    async def handle(path: Path) -> None:
        if path.name == "inflight.dat":
            await release.wait()
        handled.append(path)

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log, resume)  # type: ignore[arg-type]
    )
    for name in ("inflight.dat", "queued1.dat", "queued2.dat"):
        q.put_nowait(Path(name))
    await _settle()
    assert not handled, "first file should still be in flight"

    # User hits Pause Sync while the backlog is sitting behind the slow upload.
    resume.clear()
    release.set()
    await _settle(50)

    assert handled == [Path("inflight.dat")], "only the in-flight file may complete"
    assert q.qsize() == 2, "the backlog stays queued, not dropped"
    assert "upload_worker_paused" in log.names()

    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker


async def test_resume_ships_the_backlog_exactly_once() -> None:
    """Unpausing drains the held backlog, with no file handled twice."""
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    resume = asyncio.Event()
    resume.set()
    release = asyncio.Event()
    handled: list[Path] = []

    async def handle(path: Path) -> None:
        if path.name == "inflight.dat":
            await release.wait()
        handled.append(path)

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log, resume)  # type: ignore[arg-type]
    )
    for name in ("inflight.dat", "queued1.dat", "queued2.dat"):
        q.put_nowait(Path(name))
    await _settle()
    resume.clear()
    release.set()
    await _settle(50)
    assert handled == [Path("inflight.dat")]

    resume.set()
    await asyncio.wait_for(q.join(), timeout=5)
    await _settle()

    assert handled == [Path("inflight.dat"), Path("queued1.dat"), Path("queued2.dat")]
    assert len(handled) == len(set(handled)), "no file may be handled twice"
    assert "upload_worker_resumed" in log.names()

    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker


async def test_file_arriving_during_pause_is_held_not_shipped() -> None:
    """A path that lands while the worker waits on get() is held, not shipped."""
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    resume = asyncio.Event()
    resume.set()
    handled: list[Path] = []

    async def handle(path: Path) -> None:
        handled.append(path)

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log, resume)  # type: ignore[arg-type]
    )
    # Worker is parked on an empty queue; pause, then a late requeue arrives.
    await _settle(5)
    resume.clear()
    q.put_nowait(Path("late.dat"))
    await _settle(50)

    assert handled == [], "nothing may ship while paused"
    assert "upload_held_paused" in log.names()

    resume.set()
    await _settle(50)
    assert handled == [Path("late.dat")], "the held file ships once on resume"

    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker


def test_paused_tray_ignores_uploading_and_idle() -> None:
    """A paused tray must not flip back to uploading or idle behind the user."""
    from deep_analysis_agent import tray as tray_mod

    icon = tray_mod.TrayIcon(config=AppConfig(), version="0.0.0-test")
    icon._paused = True
    icon.set_state("paused")
    icon.set_state("uploading")
    assert icon._state == "paused"
    icon.set_state("idle")
    assert icon._state == "paused"
    # Errors are still allowed to surface.
    icon.set_state("error")
    assert icon._state == "error"


# --- Stale queue entries are revalidated at dequeue (Codex P2 on PR #52) ---


def _age(path: Path, seconds: float) -> None:
    """Backdate a file's mtime so it reads as settled."""
    import os

    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def test_dequeue_readiness_states(tmp_path: Path) -> None:
    settled = tmp_path / "settled.dat"
    settled.write_bytes(b"done")
    _age(settled, 120)
    assert main_mod.dequeue_readiness(settled, 60) == "ready"

    fresh = tmp_path / "fresh.dat"
    fresh.write_bytes(b"still writing")
    assert main_mod.dequeue_readiness(fresh, 60) == "unstable"

    assert main_mod.dequeue_readiness(tmp_path / "nope.dat", 60) == "gone"


async def test_file_modified_after_queueing_is_not_shipped_stale(tmp_path: Path) -> None:
    """A queue entry whose file changed while it waited must not be shipped."""
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    handled: list[Path] = []

    stale = tmp_path / "decklist.xml"
    stale.write_bytes(b"v1")
    _age(stale, 300)
    good = tmp_path / "match.dat"
    good.write_bytes(b"payload")
    _age(good, 300)

    async def handle(path: Path) -> None:
        handled.append(path)

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log, None, 60.0)  # type: ignore[arg-type]
    )
    q.put_nowait(stale)
    q.put_nowait(good)
    # The user edits the decklist while it sits in the queue.
    stale.write_bytes(b"v2 half writ")

    await asyncio.wait_for(q.join(), timeout=5)
    await _settle()

    assert handled == [good], "the modified file must not ship in its stale state"
    assert "upload_deferred_unstable" in log.names()

    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker


async def test_unstable_file_requeue_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that never settles is given up on instead of looping forever."""
    monkeypatch.setattr(main_mod, "_REVALIDATE_DELAY", 0.01)
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    handled: list[Path] = []

    churning = tmp_path / "churn.dat"
    churning.write_bytes(b"x")

    async def handle(path: Path) -> None:  # pragma: no cover, must never run
        handled.append(path)

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log, None, 60.0)  # type: ignore[arg-type]
    )
    q.put_nowait(churning)
    for _ in range(200):
        await asyncio.sleep(0.01)
        churning.write_bytes(b"still going")
        if "upload_dropped_still_changing" in log.names():
            break

    assert handled == [], "a file that never settles must not be shipped"
    assert "upload_dropped_still_changing" in log.names()
    assert log.names().count("upload_deferred_unstable") == main_mod._MAX_REVALIDATIONS

    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker


async def test_unstable_file_ships_once_it_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deferred file is requeued, not dropped, and ships when it settles."""
    monkeypatch.setattr(main_mod, "_REVALIDATE_DELAY", 0.05)
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    handled: list[Path] = []

    late = tmp_path / "late.dat"
    late.write_bytes(b"writing")

    async def handle(path: Path) -> None:
        handled.append(path)

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log, None, 60.0)  # type: ignore[arg-type]
    )
    q.put_nowait(late)
    await _settle(5)
    assert handled == []
    # The write finishes and the file settles before the requeue lands.
    _age(late, 300)
    for _ in range(200):
        await asyncio.sleep(0.01)
        if handled:
            break

    assert handled == [late]
    assert "upload_deferred_unstable" in log.names()
    assert "upload_dropped_still_changing" not in log.names()

    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker


async def test_vanished_file_is_skipped_not_failed(tmp_path: Path) -> None:
    """A queued path deleted before its turn is skipped quietly."""
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    handled: list[Path] = []

    async def handle(path: Path) -> None:  # pragma: no cover, must never run
        handled.append(path)

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log, None, 60.0)  # type: ignore[arg-type]
    )
    q.put_nowait(tmp_path / "deleted.dat")
    await asyncio.wait_for(q.join(), timeout=5)
    await _settle()

    assert handled == []
    assert "skip_vanished_before_upload" in log.names()
    assert tray.states == []

    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker


async def test_held_file_keeps_its_queue_accounting() -> None:
    """A held file is not marked done until it actually ships."""
    q: asyncio.Queue[Path] = asyncio.Queue()
    log = _RecordingLog()
    tray = _StubTray()
    resume = asyncio.Event()
    resume.set()
    handled: list[Path] = []

    async def handle(path: Path) -> None:
        handled.append(path)

    worker = asyncio.create_task(
        main_mod.upload_worker(q, handle, tray, log, resume)  # type: ignore[arg-type]
    )
    await _settle(5)
    resume.clear()
    q.put_nowait(Path("held.dat"))
    await _settle(30)

    assert handled == []
    joined = asyncio.create_task(q.join())
    await _settle(10)
    assert not joined.done(), "join() must not report done while a file is held"

    resume.set()
    await asyncio.wait_for(joined, timeout=5)
    assert handled == [Path("held.dat")]

    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker


async def test_deferred_drain_stops_when_paused_mid_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pause landing mid-drain leaves the rest of the batch deferred."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTrayWithNotify()
    log = _RecordingLog()

    paths = []
    for i in range(3):
        f = tmp_path / f"m{i}.dat"
        f.write_bytes(f"payload{i}".encode())
        paths.append(f)

    shipped: list[Path] = []

    async def fake_ship(*args: object, **_kw: object) -> object:
        shipped.append(args[2])  # type: ignore[arg-type]
        # The user pauses partway through the drain.
        tray._paused = True
        return MagicMock(deduped=False, upload_id=1)

    monkeypatch.setattr(shipper, "ship_file", AsyncMock(side_effect=fake_ship))

    deferred = list(paths)
    await main_mod._drain_deferred(
        deferred,
        cfg,
        dedup,
        tray,  # type: ignore[arg-type]
        asyncio.Event(),
        asyncio.Event(),
        log,  # type: ignore[arg-type]
    )

    assert shipped == [paths[0]], "the drain must stop at the pause, not finish the batch"
    assert deferred == paths[1:], "the rest of the batch stays deferred"
    assert "drain_interrupted" in log.names()
    dedup.close()


async def test_deferred_drain_declines_to_start_while_paused(tmp_path: Path) -> None:
    """A drain triggered while already paused ships nothing."""
    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    dedup = DedupStore(tmp_path / "dedup.db")
    tray = _StubTrayWithNotify()
    tray._paused = True
    log = _RecordingLog()

    f = tmp_path / "m.dat"
    f.write_bytes(b"payload")
    deferred = [f]

    await main_mod._drain_deferred(
        deferred,
        cfg,
        dedup,
        tray,  # type: ignore[arg-type]
        asyncio.Event(),
        asyncio.Event(),
        log,  # type: ignore[arg-type]
    )

    assert deferred == [f]
    assert "drain_deferred_paused" in log.names()
    dedup.close()
