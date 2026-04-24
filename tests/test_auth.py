"""Tests for auth.register + auth.heartbeat."""

from __future__ import annotations

import httpx
import pytest
import respx

from deep_analysis_agent import auth

SERVER = "https://example.test"


async def test_register_success() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/register").respond(
            200, json={"agent_id": "a-1", "api_token": "tok-abc", "user_id": 42}
        )
        result = await auth.register(
            SERVER, code="AB34-XY78", machine_name="scott-laptop", client_version="0.4.0"
        )
    assert result.agent_id == "a-1"
    assert result.api_token == "tok-abc"
    assert result.user_id == 42


async def test_register_401() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/register").respond(401, json={"error": "invalid"})
        with pytest.raises(auth.RegistrationError):
            await auth.register(SERVER, code="BAD", machine_name="m", client_version="0.4.0")


async def test_heartbeat_success() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/heartbeat").respond(
            200,
            json={
                "status": "ok",
                "registered_at": "2026-04-23T14:55:00Z",
                "revoked": False,
            },
        )
        result = await auth.heartbeat(SERVER, api_token="tok", client_version="0.4.0")
    assert result.status == "ok"
    assert result.revoked is False
    assert result.registered_at is not None


async def test_heartbeat_revoked() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/heartbeat").respond(
            200,
            json={
                "status": "ok",
                "registered_at": "2026-04-23T14:55:00Z",
                "revoked": True,
            },
        )
        result = await auth.heartbeat(SERVER, api_token="tok", client_version="0.4.0")
    assert result.revoked is True


async def test_heartbeat_401() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/heartbeat").respond(401, json={"error": "revoked"})
        with pytest.raises(auth.HeartbeatError):
            await auth.heartbeat(SERVER, api_token="bad", client_version="0.4.0")


async def test_register_network_error() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/register").mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(auth.RegistrationError):
            await auth.register(SERVER, code="X", machine_name="m", client_version="0.4.0")
