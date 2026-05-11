"""Tests for auth.register + auth.heartbeat."""

from __future__ import annotations

import json

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


async def test_register_with_credentials_success() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/register-with-credentials").respond(
            201, json={"agent_id": "b-2", "api_token": "key-xyz", "user_id": 42}
        )
        result = await auth.register_with_credentials(
            SERVER,
            email="user@example.com",
            password="hunter2",
            agent_name="scott-laptop",
            client_version="0.4.5",
        )
    assert result.agent_id == "b-2"
    assert result.api_token == "key-xyz"
    assert result.user_id == 42


async def test_register_with_credentials_sends_client_version() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        route = mock.post("/auth/agent/register-with-credentials").respond(
            201, json={"agent_id": "b-2", "api_token": "key-xyz", "user_id": 42}
        )
        await auth.register_with_credentials(
            SERVER,
            email="user@example.com",
            password="hunter2",
            agent_name="scott-laptop",
            client_version="0.4.5",
        )
        assert route.called
        body = json.loads(mock.calls.last.request.content)
    assert body["client_version"] == "0.4.5"


async def test_register_with_credentials_401() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/register-with-credentials").respond(401, json={"error": "nope"})
        with pytest.raises(auth.RegistrationError):
            await auth.register_with_credentials(
                SERVER, email="u@x", password="bad", agent_name="m", client_version="0.4.5"
            )


async def test_register_with_credentials_403() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/register-with-credentials").respond(403, json={"error": "admin"})
        with pytest.raises(auth.RegistrationError):
            await auth.register_with_credentials(
                SERVER, email="admin@x", password="x", agent_name="m", client_version="0.4.5"
            )


async def test_register_with_credentials_409() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/register-with-credentials").respond(409, json={"error": "rate"})
        with pytest.raises(auth.RegistrationError):
            await auth.register_with_credentials(
                SERVER, email="u@x", password="x", agent_name="m", client_version="0.4.5"
            )


async def test_register_with_credentials_network_error() -> None:
    async with respx.mock(base_url=SERVER) as mock:
        mock.post("/auth/agent/register-with-credentials").mock(
            side_effect=httpx.ConnectError("boom")
        )
        with pytest.raises(auth.RegistrationError):
            await auth.register_with_credentials(
                SERVER, email="u@x", password="x", agent_name="m", client_version="0.4.5"
            )
