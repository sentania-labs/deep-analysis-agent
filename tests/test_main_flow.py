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
    await main_mod._handle_file(sample, cfg, dedup, tray, asyncio.Event(), asyncio.Event(), [], log)  # type: ignore[arg-type]
    ship_mock.assert_not_called()


async def test_mark_seen_after_ship(
    ctx: tuple[AppConfig, DedupStore, _StubTray, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, dedup, tray, sample = ctx

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f2"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
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
    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
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
        return shipper.UploadResult(deduped=False, file_id="fx")

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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f2"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="i1"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="c1"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="d1"))
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

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
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
