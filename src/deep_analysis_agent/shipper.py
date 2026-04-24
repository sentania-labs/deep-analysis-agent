"""HTTP shipper — uploads MTGO `.dat`/`.log` files to the server.

Retries once on 5xx. A 409 response is treated as `deduped=True`, not
an error: the server already has this sha. The caller should still
call `dedup.mark_seen(...)` so the file is not re-queued.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger(__name__)

_CONNECT_TIMEOUT = 10.0
_TOTAL_TIMEOUT = 120.0
_RETRY_BACKOFF_SECONDS = 1.5


class ShipError(RuntimeError):
    """Upload failed after retry (or hit a non-retriable 4xx)."""


@dataclass(frozen=True)
class UploadResult:
    deduped: bool
    file_id: str | None


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(_TOTAL_TIMEOUT, connect=_CONNECT_TIMEOUT)


async def ship_file(
    server_url: str,
    api_token: str,
    path: Path,
    sha256: str,
    tls_verify: bool | str = True,
) -> UploadResult:
    """Upload a single file to POST /ingest/upload.

    The request body is `multipart/form-data` with:
      - file: the raw file contents
      - sha256: the precomputed hash (server may verify)

    Authorization: Bearer <api_token>.
    """
    url = server_url.rstrip("/") + "/ingest/upload"
    headers = {"Authorization": f"Bearer {api_token}"}

    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            with path.open("rb") as fh:
                files = {"file": (path.name, fh, "application/octet-stream")}
                data = {"sha256": sha256}
                async with httpx.AsyncClient(timeout=_timeout(), verify=tls_verify) as client:
                    resp = await client.post(url, headers=headers, files=files, data=data)
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning("ship_network_error", attempt=attempt, error=str(exc))
            if attempt == 1:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                continue
            raise ShipError(f"network error after retry: {exc}") from exc

        if resp.status_code == 409:
            return UploadResult(deduped=True, file_id=None)
        if 500 <= resp.status_code < 600:
            logger.warning("ship_server_error", attempt=attempt, status=resp.status_code)
            if attempt == 1:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                continue
            raise ShipError(f"server error {resp.status_code} after retry")
        if resp.status_code >= 400:
            raise ShipError(f"server returned {resp.status_code}: {resp.text[:200]}")

        payload = resp.json()
        return UploadResult(
            deduped=bool(payload.get("deduped", False)),
            file_id=payload.get("file_id"),
        )

    # Unreachable, but keeps mypy happy.
    raise ShipError(f"exhausted retries: {last_exc}")
