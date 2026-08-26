"""Shared test fixtures.

The helpers here are the single place the ingest upload contract is
encoded on the test side. They mirror the server's ``UploadResponse``
(deep-analysis-server: ``services/ingest/ingest_service/schemas.py``)
exactly, so a fake upload response in any test cannot quietly describe
an API the server does not actually serve.

Agent issue #40 happened because each test hand-rolled its own upload
payload with a ``file_id`` key that the server has never returned. Build
fake upload responses through :func:`upload_response` instead.
"""

from __future__ import annotations

from typing import Any

# Exact field set of the server's ``UploadResponse``. If the server adds,
# removes, or renames a field, change it here and every upload test moves
# with it.
UPLOAD_RESPONSE_FIELDS = frozenset({"sha256", "size_bytes", "deduped", "upload_id"})

# ``POST /ingest/upload`` is declared with ``status_code=201``.
UPLOAD_CREATED_STATUS = 201


def upload_response(
    *,
    deduped: bool,
    upload_id: int,
    sha256: str = "a" * 64,
    size_bytes: int = 17,
) -> dict[str, Any]:
    """Build a JSON body shaped exactly like the server's ``UploadResponse``.

    ``deduped`` and ``upload_id`` are required because they are the two
    fields the agent actually consumes. The build is validated against
    :data:`UPLOAD_RESPONSE_FIELDS` so a stray or missing key fails loudly
    rather than silently teaching the agent a wrong contract.
    """
    body: dict[str, Any] = {
        "sha256": sha256,
        "size_bytes": size_bytes,
        "deduped": deduped,
        "upload_id": upload_id,
    }
    assert set(body) == UPLOAD_RESPONSE_FIELDS, (
        f"upload_response drifted from the server contract: "
        f"{sorted(set(body) ^ UPLOAD_RESPONSE_FIELDS)}"
    )
    return body
