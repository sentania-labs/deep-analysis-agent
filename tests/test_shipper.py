"""Tests for shipper.ship_file."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import respx
from httpx import Response

from deep_analysis_agent import shipper

from .conftest import UPLOAD_CREATED_STATUS, UPLOAD_RESPONSE_FIELDS, upload_response

SERVER = "https://example.test"


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    p = tmp_path / "match.dat"
    p.write_bytes(b"fake mtgo payload")
    return p


async def test_ship_success(sample_file: Path) -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").respond(
            UPLOAD_CREATED_STATUS, json=upload_response(deduped=False, upload_id=101)
        )
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.deduped is False
    assert result.upload_id == 101


async def test_ship_dedup_flag(sample_file: Path) -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").respond(
            UPLOAD_CREATED_STATUS, json=upload_response(deduped=True, upload_id=101)
        )
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
        Response(UPLOAD_CREATED_STATUS, json=upload_response(deduped=False, upload_id=101)),
    ]
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=responses)
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.deduped is False
    assert result.upload_id == 101


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
        return Response(UPLOAD_CREATED_STATUS, json=upload_response(deduped=False, upload_id=201))

    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=_capture)
        result = await shipper.ship_file(
            SERVER,
            "tok",
            sample_file,
            sha256="a" * 64,
            content_type="decklist",
        )
    assert result.upload_id == 201


async def test_ship_sends_original_filename(sample_file: Path) -> None:
    """original_filename form field is included when provided."""
    import httpx

    def _capture(request: object) -> Response:
        assert isinstance(request, httpx.Request)
        body = request.content
        assert b"original_filename" in body
        assert b"grouping 12345.xml" in body
        return Response(UPLOAD_CREATED_STATUS, json=upload_response(deduped=False, upload_id=202))

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
    assert result.upload_id == 202


async def test_ship_default_content_type(sample_file: Path) -> None:
    """Default content_type is match-log when not specified."""
    import httpx

    def _capture(request: object) -> Response:
        assert isinstance(request, httpx.Request)
        body = request.content
        assert b"content_type" in body
        assert b"match-log" in body
        return Response(UPLOAD_CREATED_STATUS, json=upload_response(deduped=False, upload_id=203))

    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=_capture)
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.upload_id == 203


async def test_ship_sends_file_mtime(sample_file: Path) -> None:
    """file_mtime form field is included when provided."""
    import httpx

    def _capture(request: object) -> Response:
        assert isinstance(request, httpx.Request)
        body = request.content
        assert b"file_mtime" in body
        return Response(UPLOAD_CREATED_STATUS, json=upload_response(deduped=False, upload_id=204))

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
    assert result.upload_id == 204


async def test_ship_sends_agent_classification(sample_file: Path) -> None:
    """agent_classification form field is included when provided."""
    import httpx

    def _capture(request: object) -> Response:
        assert isinstance(request, httpx.Request)
        body = request.content
        assert b"agent_classification" in body
        assert b"inconclusive" in body
        return Response(UPLOAD_CREATED_STATUS, json=upload_response(deduped=False, upload_id=301))

    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=_capture)
        result = await shipper.ship_file(
            SERVER,
            "tok",
            sample_file,
            sha256="a" * 64,
            agent_classification="inconclusive",
        )
    assert result.upload_id == 301


async def test_ship_omits_agent_classification_when_none(sample_file: Path) -> None:
    """No agent_classification field when caller leaves it unset."""
    import httpx

    def _capture(request: object) -> Response:
        assert isinstance(request, httpx.Request)
        body = request.content
        assert b"agent_classification" not in body
        return Response(UPLOAD_CREATED_STATUS, json=upload_response(deduped=False, upload_id=302))

    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=_capture)
        await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)


async def test_ship_omits_file_mtime_when_none(sample_file: Path) -> None:
    """file_mtime form field is NOT included when None (default)."""
    import httpx

    def _capture(request: object) -> Response:
        assert isinstance(request, httpx.Request)
        body = request.content
        assert b"file_mtime" not in body
        return Response(UPLOAD_CREATED_STATUS, json=upload_response(deduped=False, upload_id=205))

    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").mock(side_effect=_capture)
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.upload_id == 205


# ---------------------------------------------------------------------------
# Contract guards (agent issue #40)
#
# These tests exist so the agent's idea of the upload response cannot drift
# away from the server's ``UploadResponse`` without something going red.
# ---------------------------------------------------------------------------


def test_upload_result_fields_exist_on_the_server_contract() -> None:
    """Every field UploadResult carries must be a real UploadResponse field.

    UploadResult is allowed to carry a subset (it ignores sha256 and
    size_bytes), but it must never invent a field the server does not
    return. Renaming ``upload_id`` back to something like ``file_id``
    fails here.
    """
    carried = {f.name for f in dataclasses.fields(shipper.UploadResult)}
    assert carried <= UPLOAD_RESPONSE_FIELDS, (
        f"UploadResult carries fields the server never returns: "
        f"{sorted(carried - UPLOAD_RESPONSE_FIELDS)}"
    )
    assert "upload_id" in carried


def test_upload_response_helper_matches_the_contract() -> None:
    """The shared fake mirrors the server body exactly, no more, no less."""
    assert set(upload_response(deduped=False, upload_id=7)) == UPLOAD_RESPONSE_FIELDS


async def test_ship_reads_upload_id_not_file_id(sample_file: Path) -> None:
    """A body carrying only the old ``file_id`` key yields no upload id.

    This is the regression the agent shipped for real: it read a key the
    server has never returned, so every success logged ``None``.
    """
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").respond(
            UPLOAD_CREATED_STATUS, json={"deduped": False, "file_id": "abc"}
        )
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.upload_id is None


async def test_ship_409_has_no_upload_id(sample_file: Path) -> None:
    """A 409 dedup short-circuit returns no upload id, by design."""
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").respond(409, json={"error": "already uploaded"})
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.deduped is True
    assert result.upload_id is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (12345, 12345),
        ("12345", 12345),
        (None, None),
        ("not-a-number", None),
        (True, None),
    ],
)
async def test_ship_upload_id_coercion(
    sample_file: Path, raw: object, expected: int | None
) -> None:
    """Non-int ``upload_id`` values degrade to None rather than blowing up."""
    body: dict[str, object] = {
        "sha256": "a" * 64,
        "size_bytes": 17,
        "deduped": False,
        "upload_id": raw,
    }
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/ingest/upload").respond(UPLOAD_CREATED_STATUS, json=body)
        result = await shipper.ship_file(SERVER, "tok", sample_file, sha256="a" * 64)
    assert result.upload_id == expected
