"""Tests for CardDataSource version-check-and-ship logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deep_analysis_agent import shipper
from deep_analysis_agent.card_data_source import (
    _META_KEY,
    check_and_ship,
    compute_combined_hash,
    find_card_data_source_dir,
    list_xml_files,
)
from deep_analysis_agent.config import AppConfig
from deep_analysis_agent.dedup import DedupStore

# --- list_xml_files ---


def test_list_xml_files_returns_sorted(tmp_path: Path) -> None:
    (tmp_path / "client_MH3.xml").write_text("<cards/>")
    (tmp_path / "client_10E.xml").write_text("<cards/>")
    (tmp_path / "CARDNAME_STRING.xml").write_text("<names/>")
    # Non-XML file should be excluded.
    (tmp_path / "readme.txt").write_text("ignore")

    result = list_xml_files(tmp_path)
    names = [p.name for p in result]
    assert names == ["CARDNAME_STRING.xml", "client_10E.xml", "client_MH3.xml"]


def test_list_xml_files_empty_dir(tmp_path: Path) -> None:
    assert list_xml_files(tmp_path) == []


def test_list_xml_files_nonexistent_dir(tmp_path: Path) -> None:
    assert list_xml_files(tmp_path / "nope") == []


def test_list_xml_files_skips_subdirectories(tmp_path: Path) -> None:
    (tmp_path / "client_MH3.xml").write_text("<cards/>")
    sub = tmp_path / "subdir.xml"
    sub.mkdir()
    result = list_xml_files(tmp_path)
    assert len(result) == 1
    assert result[0].name == "client_MH3.xml"


# --- compute_combined_hash ---


def test_combined_hash_deterministic(tmp_path: Path) -> None:
    (tmp_path / "a.xml").write_bytes(b"<a/>")
    (tmp_path / "b.xml").write_bytes(b"<b/>")
    files = list_xml_files(tmp_path)
    h1 = compute_combined_hash(files)
    h2 = compute_combined_hash(files)
    assert h1 == h2


def test_combined_hash_changes_on_content_change(tmp_path: Path) -> None:
    (tmp_path / "a.xml").write_bytes(b"<a/>")
    (tmp_path / "b.xml").write_bytes(b"<b/>")
    files = list_xml_files(tmp_path)
    h1 = compute_combined_hash(files)

    # Modify one file.
    (tmp_path / "b.xml").write_bytes(b"<b>changed</b>")
    files2 = list_xml_files(tmp_path)
    h2 = compute_combined_hash(files2)
    assert h1 != h2


def test_combined_hash_changes_on_file_added(tmp_path: Path) -> None:
    (tmp_path / "a.xml").write_bytes(b"<a/>")
    files = list_xml_files(tmp_path)
    h1 = compute_combined_hash(files)

    # Add a new file.
    (tmp_path / "c.xml").write_bytes(b"<c/>")
    files2 = list_xml_files(tmp_path)
    h2 = compute_combined_hash(files2)
    assert h1 != h2


def test_combined_hash_changes_on_file_removed(tmp_path: Path) -> None:
    (tmp_path / "a.xml").write_bytes(b"<a/>")
    (tmp_path / "b.xml").write_bytes(b"<b/>")
    files = list_xml_files(tmp_path)
    h1 = compute_combined_hash(files)

    # Remove a file.
    (tmp_path / "b.xml").unlink()
    files2 = list_xml_files(tmp_path)
    h2 = compute_combined_hash(files2)
    assert h1 != h2


def test_combined_hash_empty_list() -> None:
    """Empty file list produces a valid hash (empty SHA-256)."""
    h = compute_combined_hash([])
    assert len(h) == 64  # hex digest length


def test_combined_hash_incorporates_filename(tmp_path: Path) -> None:
    """Same content but different filenames should produce different hashes."""
    dir1 = tmp_path / "d1"
    dir1.mkdir()
    (dir1 / "alpha.xml").write_bytes(b"<same/>")

    dir2 = tmp_path / "d2"
    dir2.mkdir()
    (dir2 / "beta.xml").write_bytes(b"<same/>")

    h1 = compute_combined_hash(list_xml_files(dir1))
    h2 = compute_combined_hash(list_xml_files(dir2))
    assert h1 != h2


# --- find_card_data_source_dir ---


def test_find_card_data_source_dir_found(tmp_path: Path) -> None:
    cds = tmp_path / "hash1" / "hash2" / "mtgo..tion_abc" / "Data" / "CardDataSource"
    cds.mkdir(parents=True)
    (cds / "client_MH3.xml").write_text("<cards/>")
    result = find_card_data_source_dir(tmp_path)
    assert result is not None
    assert result == cds


def test_find_card_data_source_dir_not_found(tmp_path: Path) -> None:
    result = find_card_data_source_dir(tmp_path)
    assert result is None


def test_find_card_data_source_dir_empty_cds(tmp_path: Path) -> None:
    """A CardDataSource dir with no XML files is skipped."""
    cds = tmp_path / "Data" / "CardDataSource"
    cds.mkdir(parents=True)
    result = find_card_data_source_dir(tmp_path)
    assert result is None


def test_find_card_data_source_dir_nonexistent(tmp_path: Path) -> None:
    result = find_card_data_source_dir(tmp_path / "nope")
    assert result is None


# --- Meta key-value store (dedup) ---


def test_meta_get_set(tmp_path: Path) -> None:
    store = DedupStore(tmp_path / "dedup.db")
    assert store.get_meta("foo") is None
    store.set_meta("foo", "bar")
    assert store.get_meta("foo") == "bar"


def test_meta_overwrite(tmp_path: Path) -> None:
    store = DedupStore(tmp_path / "dedup.db")
    store.set_meta("key", "v1")
    store.set_meta("key", "v2")
    assert store.get_meta("key") == "v2"


def test_meta_persists(tmp_path: Path) -> None:
    db = tmp_path / "dedup.db"
    s1 = DedupStore(db)
    s1.set_meta("k", "val")
    s1.close()

    s2 = DedupStore(db)
    assert s2.get_meta("k") == "val"


# --- check_and_ship integration ---


@pytest.fixture
def cds_setup(tmp_path: Path) -> tuple[AppConfig, DedupStore, Path]:
    """Create a config, dedup store, and CardDataSource directory with test files."""
    cds_dir = tmp_path / "CardDataSource"
    cds_dir.mkdir()
    (cds_dir / "client_MH3.xml").write_bytes(b"<set>MH3</set>")
    (cds_dir / "client_10E.xml").write_bytes(b"<set>10E</set>")
    (cds_dir / "CARDNAME_STRING.xml").write_bytes(b"<names/>")

    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.mtgo.card_data_source_dir = cds_dir
    cfg.mtgo.card_data_source_enabled = True

    dedup = DedupStore(tmp_path / "dedup.db")
    return cfg, dedup, cds_dir


async def test_check_and_ship_first_run(
    cds_setup: tuple[AppConfig, DedupStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First run ships all files and stores the combined hash."""
    cfg, dedup, cds_dir = cds_setup

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
    monkeypatch.setattr("deep_analysis_agent.card_data_source.ship_file", ship_mock)

    await check_and_ship(cfg, dedup)

    assert ship_mock.call_count == 3
    # Combined hash should be stored.
    assert dedup.get_meta(_META_KEY) is not None


async def test_check_and_ship_no_change(
    cds_setup: tuple[AppConfig, DedupStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second run with no changes should not ship anything."""
    cfg, dedup, cds_dir = cds_setup

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
    monkeypatch.setattr("deep_analysis_agent.card_data_source.ship_file", ship_mock)

    await check_and_ship(cfg, dedup)
    assert ship_mock.call_count == 3

    # Second run — no changes.
    ship_mock.reset_mock()
    await check_and_ship(cfg, dedup)
    assert ship_mock.call_count == 0


async def test_check_and_ship_after_change(
    cds_setup: tuple[AppConfig, DedupStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a file changes, the new version is shipped."""
    cfg, dedup, cds_dir = cds_setup

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
    monkeypatch.setattr("deep_analysis_agent.card_data_source.ship_file", ship_mock)

    await check_and_ship(cfg, dedup)
    ship_mock.reset_mock()

    # Modify a file.
    (cds_dir / "client_MH3.xml").write_bytes(b"<set>MH3_v2</set>")
    await check_and_ship(cfg, dedup)

    # Only the changed file needs new shipping (others are dedup-skipped locally).
    assert ship_mock.call_count >= 1


async def test_check_and_ship_disabled(
    cds_setup: tuple[AppConfig, DedupStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When disabled, nothing is shipped."""
    cfg, dedup, cds_dir = cds_setup
    cfg.mtgo.card_data_source_enabled = False

    ship_mock = AsyncMock()
    monkeypatch.setattr("deep_analysis_agent.card_data_source.ship_file", ship_mock)

    await check_and_ship(cfg, dedup)
    ship_mock.assert_not_called()


async def test_check_and_ship_no_token(
    cds_setup: tuple[AppConfig, DedupStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an API token, files are not shipped."""
    cfg, dedup, cds_dir = cds_setup
    cfg.agent.api_token = None

    ship_mock = AsyncMock()
    monkeypatch.setattr("deep_analysis_agent.card_data_source.ship_file", ship_mock)

    await check_and_ship(cfg, dedup)
    ship_mock.assert_not_called()


async def test_check_and_ship_partial_failure(
    cds_setup: tuple[AppConfig, DedupStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If some files fail to ship, combined hash is NOT stored."""
    cfg, dedup, cds_dir = cds_setup

    call_count = 0

    async def _flaky_ship(*args: object, **kwargs: object) -> shipper.UploadResult:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise shipper.ShipError("network fail")
        return shipper.UploadResult(deduped=False, file_id="ok")

    monkeypatch.setattr("deep_analysis_agent.card_data_source.ship_file", _flaky_ship)

    await check_and_ship(cfg, dedup)
    # Combined hash should NOT be stored because of the failure.
    assert dedup.get_meta(_META_KEY) is None


async def test_check_and_ship_auto_detect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-detect finds CardDataSource under the MTGO log_dir tree."""
    # Create nested MTGO-like structure.
    cds = tmp_path / "h1" / "h2" / "mtgo..tion_abc" / "Data" / "CardDataSource"
    cds.mkdir(parents=True)
    (cds / "client_MH3.xml").write_bytes(b"<set>MH3</set>")

    cfg = AppConfig()
    cfg.server.url = "https://example.test"
    cfg.agent.api_token = "tok"
    cfg.mtgo.log_dir = tmp_path
    cfg.mtgo.card_data_source_dir = None  # auto-detect
    cfg.mtgo.card_data_source_enabled = True

    dedup = DedupStore(tmp_path / "dedup.db")

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
    monkeypatch.setattr("deep_analysis_agent.card_data_source.ship_file", ship_mock)

    await check_and_ship(cfg, dedup)
    assert ship_mock.call_count == 1


async def test_check_and_ship_uses_reference_data_content_type(
    cds_setup: tuple[AppConfig, DedupStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shipped files use content_type=reference-data."""
    cfg, dedup, cds_dir = cds_setup

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
    monkeypatch.setattr("deep_analysis_agent.card_data_source.ship_file", ship_mock)

    await check_and_ship(cfg, dedup)

    for call in ship_mock.call_args_list:
        assert call.kwargs["content_type"] == "reference-data"


async def test_check_and_ship_preserves_original_filename(
    cds_setup: tuple[AppConfig, DedupStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each file is shipped with its original filename."""
    cfg, dedup, cds_dir = cds_setup

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
    monkeypatch.setattr("deep_analysis_agent.card_data_source.ship_file", ship_mock)

    await check_and_ship(cfg, dedup)

    filenames = {call.kwargs["original_filename"] for call in ship_mock.call_args_list}
    assert filenames == {"CARDNAME_STRING.xml", "client_10E.xml", "client_MH3.xml"}


async def test_check_and_ship_dedup_skips_unchanged_files(
    cds_setup: tuple[AppConfig, DedupStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Files already in dedup store are skipped (no ship_file call)."""
    cfg, dedup, cds_dir = cds_setup

    # Pre-mark one file as seen.
    f = cds_dir / "client_10E.xml"
    sha = dedup.hash_file(f)
    dedup.mark_seen(sha, f)

    ship_mock = AsyncMock(return_value=shipper.UploadResult(deduped=False, file_id="f1"))
    monkeypatch.setattr("deep_analysis_agent.card_data_source.ship_file", ship_mock)

    await check_and_ship(cfg, dedup)

    # Only 2 files should be shipped (the third was already seen).
    assert ship_mock.call_count == 2
    shipped_names = {call.kwargs["original_filename"] for call in ship_mock.call_args_list}
    assert "client_10E.xml" not in shipped_names
