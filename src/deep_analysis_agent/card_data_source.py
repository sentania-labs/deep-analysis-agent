"""CardDataSource version-check-and-ship.

MTGO stores a card catalog in Data/CardDataSource/ — per-set XML files
(client_MH3.xml, etc.) plus lookup tables (CARDNAME_STRING.xml, etc.).
This data only changes when WotC pushes a client update.

On startup (and periodically), the agent computes a combined hash of all
XML files in the directory.  If the hash differs from the last shipped
version, every file is shipped to the server as ``reference-data``.
Per-file SHA-256 dedup means unchanged files between versions are
automatically skipped server-side (409).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import structlog

from .config import AppConfig
from .dedup import DedupStore
from .shipper import ShipError, ship_file

logger = structlog.get_logger(__name__)

_META_KEY = "card_data_source_hash"


def find_card_data_source_dir(log_dir: Path) -> Path | None:
    """Try to locate CardDataSource by searching near the MTGO data path.

    The MTGO data directory structure under ``%LOCALAPPDATA%\\Apps\\2.0``
    is::

        <hash1>/<hash2>/mtgo..tion_<hash>/Data/CardDataSource/
        <hash1>/<hash2>/mtgo..tion_<hash>/Data/AppFiles/<hash>/

    ``log_dir`` typically points to ``Apps/2.0``.  We search for a
    directory named ``CardDataSource`` under it.  Returns the first
    match, or None if nothing is found.
    """
    if not log_dir.is_dir():
        return None
    # rglob can be expensive under Apps/2.0, but CardDataSource is only
    # a few levels deep.  Limit depth by iterating manually.
    candidates: list[Path] = []
    try:
        for candidate in log_dir.rglob("CardDataSource"):
            if candidate.is_dir():
                # Sanity-check: should contain at least one .xml file.
                xml_files = list(candidate.glob("*.xml"))
                if xml_files:
                    candidates.append(candidate)
    except OSError:
        pass
    if not candidates:
        return None
    # MTGO ClickOnce installs can leave multiple versioned directories.
    # Pick the one with the most recent mtime (latest MTGO version).
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def list_xml_files(directory: Path) -> list[Path]:
    """Return sorted list of .xml files in the CardDataSource directory."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".xml")


def compute_combined_hash(files: list[Path]) -> str:
    """Compute a combined SHA-256 over the sorted file list.

    For each file, the filename and file content hash are fed into a
    master digest.  This means the combined hash changes when any file
    is added, removed, renamed, or modified.
    """
    master = hashlib.sha256()
    for f in files:
        master.update(f.name.encode("utf-8"))
        file_hash = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                file_hash.update(chunk)
        master.update(file_hash.hexdigest().encode("utf-8"))
    return master.hexdigest()


async def check_and_ship(
    config: AppConfig,
    dedup: DedupStore,
) -> None:
    """Check CardDataSource for changes and ship new/modified files.

    Resolves the CardDataSource directory (explicit config or
    auto-detect), computes a combined hash, and ships all files if the
    hash has changed since the last successful ship.
    """
    log = logger.bind()

    if not config.mtgo.card_data_source_enabled:
        log.debug("card_data_source_disabled")
        return

    # Resolve the directory.
    cds_dir = config.mtgo.card_data_source_dir
    if cds_dir is None:
        cds_dir = find_card_data_source_dir(config.mtgo.log_dir)
    if cds_dir is None or not cds_dir.is_dir():
        log.info("card_data_source_not_found", log_dir=str(config.mtgo.log_dir))
        return

    xml_files = list_xml_files(cds_dir)
    if not xml_files:
        log.info("card_data_source_empty", dir=str(cds_dir))
        return

    combined_hash = compute_combined_hash(xml_files)
    stored_hash = dedup.get_meta(_META_KEY)

    if combined_hash == stored_hash:
        log.info("card_data_source_up_to_date", file_count=len(xml_files))
        return

    log.info(
        "card_data_source_changed",
        file_count=len(xml_files),
        dir=str(cds_dir),
    )

    if not config.agent.api_token:
        log.warning("card_data_source_skip_no_token")
        return

    shipped = 0
    failed = 0
    for xml_file in xml_files:
        sha = dedup.hash_file(xml_file)
        try:
            result = await ship_file(
                config.server.url,
                config.agent.api_token,
                xml_file,
                sha,
                tls_verify=config.server.tls_verify,
                content_type="reference-data",
                original_filename=xml_file.name,
            )
            dedup.mark_seen(sha, xml_file)
            shipped += 1
            log.info(
                "card_data_source_file_shipped",
                file=xml_file.name,
                deduped=result.deduped,
            )
        except ShipError:
            log.exception("card_data_source_ship_failed", file=xml_file.name)
            failed += 1

    if failed == 0:
        dedup.set_meta(_META_KEY, combined_hash)
        log.info("card_data_source_complete", shipped=shipped)
    else:
        log.warning(
            "card_data_source_partial",
            shipped=shipped,
            failed=failed,
        )
