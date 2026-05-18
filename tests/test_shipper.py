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


async def test_ship_sends_content_type(sample_file: Path) -> None:
    """content_type form field is included in the upload request."""

    def _capture(request: object) -> Response:
        # respx passes an httpx.Request; extract multipart fields.
        import httpx

        assert isinstance(request, httpx.Request)
        # The multipart body is already encoded; check the raw bytes.
        body = request.content
        assert b"content_type" in body
        assert b"decklist" in body
        return Response(200, json={"deduped": False, "file_id": "x1"})

    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=_capture)
        result = await shipper.ship_file(
            SERVER,
            "tok",
            sample_file,
            sha256="a" * 64,
            content_type="decklist",
        )
    assert result.file_id == "x1"


async def test_ship_sends_original_filename(sample_file: Path) -> None:
    """original_filename form field is included when provided."""
    import httpx

    def _capture(request: object) -> Response:
        assert isinstance(request, httpx.Request)
        body = request.content
        assert b"original_filename" in body
        assert b"grouping 12345.xml" in body
        return Response(200, json={"deduped": False, "file_id": "x2"})

    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=_capture)
        result = await shipper.ship_file(
            SERVER,
            "tok",
            sample_file,
            sha256="a" * 64,
            content_type="decklist",
            original_filename="grouping 12345.xml",
        )
    assert result.file_id == "x2"


async def test_ship_default_content_type(sample_file: Path) -> None:
    """Default content_type is match-log when not specified."""
    import httpx

    def _capture(request: object) -> Response:
        assert isinstance(request, httpx.Request)
        body = request.content
        assert b"content_type" in body
        assert b"match-log" in body
        return Response(200, json={"deduped": False, "file_id": "x3"})

    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=_capture)
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.file_id == "x3"


async def test_ship_sends_file_mtime(sample_file: Path) -> None:
    """file_mtime form field is included when provided."""
    import httpx

    def _capture(request: object) -> Response:
        assert isinstance(request, httpx.Request)
        body = request.content
        assert b"file_mtime" in body
        return Response(200, json={"deduped": False, "file_id": "x4"})

    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=_capture)
        result = await shipper.ship_file(
            SERVER,
            "tok",
            sample_file,
            sha256="a" * 64,
            content_type="decklist",
            file_mtime=1716000000.0,
        )
    assert result.file_id == "x4"


async def test_ship_omits_file_mtime_when_none(sample_file: Path) -> None:
    """file_mtime form field is NOT included when None (default)."""
    import httpx

    def _capture(request: object) -> Response:
        assert isinstance(request, httpx.Request)
        body = request.content
        assert b"file_mtime" not in body
        return Response(200, json={"deduped": False, "file_id": "x5"})

    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=_capture)
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.file_id == "x5"
