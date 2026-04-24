"""Tests for shipper.ship_file."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response

from deep_analysis_agent import shipper

SERVER = "https://example.test"


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    p = tmp_path / "match.dat"
    p.write_bytes(b"fake mtgo payload")
    return p


async def test_ship_success(sample_file: Path) -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").respond(200, json={"deduped": False, "file_id": "abc"})
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.deduped is False
    assert result.file_id == "abc"


async def test_ship_dedup_flag(sample_file: Path) -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").respond(200, json={"deduped": True, "file_id": "abc"})
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.deduped is True


async def test_ship_409(sample_file: Path) -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").respond(409, json={"error": "already uploaded"})
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.deduped is True


async def test_ship_retry_5xx(sample_file: Path) -> None:
    responses = [
        Response(500, json={"error": "oops"}),
        Response(200, json={"deduped": False, "file_id": "abc"}),
    ]
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=responses)
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.deduped is False
    assert result.file_id == "abc"


async def test_ship_5xx_exhausts(sample_file: Path) -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").respond(502, json={"error": "bad gateway"})
        with pytest.raises(shipper.ShipError):
            await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
