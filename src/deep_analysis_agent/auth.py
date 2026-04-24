"""Server authentication — registration code exchange + heartbeat.

Mirrors `docs/agent-protocol.md` on the server side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx
import structlog

logger = structlog.get_logger(__name__)

_CONNECT_TIMEOUT = 10.0
_TOTAL_TIMEOUT = 30.0


class AuthError(RuntimeError):
    """Base class for auth failures."""


class RegistrationError(AuthError):
    """Registration code rejected or network error during /register."""


class HeartbeatError(AuthError):
    """Heartbeat call failed (network or non-401 server error)."""


@dataclass(frozen=True)
class RegistrationResult:
    agent_id: str
    api_token: str
    user_id: int


@dataclass(frozen=True)
class HeartbeatResult:
    status: str
    registered_at: datetime | None
    revoked: bool


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(_TOTAL_TIMEOUT, connect=_CONNECT_TIMEOUT)


async def register(
    server_url: str,
    code: str,
    machine_name: str,
    client_version: str,
    tls_verify: bool | str = True,
) -> RegistrationResult:
    """Exchange a registration code for an agent_id + api_token."""
    url = server_url.rstrip("/") + "/auth/agent/register"
    payload = {
        "code": code,
        "machine_name": machine_name,
        "client_version": client_version,
    }
    try:
        async with httpx.AsyncClient(timeout=_timeout(), verify=tls_verify) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise RegistrationError(f"network error: {exc}") from exc

    if resp.status_code == 401:
        raise RegistrationError("invalid or expired registration code")
    if resp.status_code >= 400:
        raise RegistrationError(f"server returned {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    return RegistrationResult(
        agent_id=data["agent_id"],
        api_token=data["api_token"],
        user_id=int(data["user_id"]),
    )


async def heartbeat(
    server_url: str,
    api_token: str,
    client_version: str,
    tls_verify: bool | str = True,
) -> HeartbeatResult:
    """POST /auth/agent/heartbeat with the bearer token."""
    url = server_url.rstrip("/") + "/auth/agent/heartbeat"
    headers = {"Authorization": f"Bearer {api_token}"}
    payload = {"client_version": client_version}
    try:
        async with httpx.AsyncClient(timeout=_timeout(), verify=tls_verify) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise HeartbeatError(f"network error: {exc}") from exc

    if resp.status_code == 401:
        raise HeartbeatError("unauthorized — token revoked or invalid")
    if resp.status_code >= 400:
        raise HeartbeatError(f"server returned {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    reg_at_raw = data.get("registered_at")
    reg_at = None
    if reg_at_raw:
        try:
            reg_at = datetime.fromisoformat(reg_at_raw.replace("Z", "+00:00"))
        except ValueError:
            reg_at = None
    return HeartbeatResult(
        status=str(data.get("status", "")),
        registered_at=reg_at,
        revoked=bool(data.get("revoked", False)),
    )
