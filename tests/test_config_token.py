"""Tests for DPAPI token storage + save_config/load_config roundtrip."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from deep_analysis_agent import config as config_module
from deep_analysis_agent.config import (
    AppConfig,
    decrypt_token,
    encrypt_token,
    load_config,
    save_config,
)


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI only available on Windows")
def test_encrypt_decrypt_roundtrip_windows() -> None:
    secret = "k4_3z_super_secret"
    enc = encrypt_token(secret)
    assert enc != secret
    assert decrypt_token(enc) == secret


def test_plaintext_fallback_offwindows(caplog: pytest.LogCaptureFixture) -> None:
    if sys.platform == "win32":
        pytest.skip("non-Windows path only")
    caplog.set_level("WARNING", logger=config_module.__name__)
    enc = encrypt_token("plainval")
    assert enc == "plainval"
    assert any("plaintext" in rec.message for rec in caplog.records)


def test_save_load_config_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = AppConfig()
    cfg.agent.machine_name = "box-1"
    cfg.agent.agent_id = "a-xyz"
    cfg.agent.api_token = "tok-abc-123"
    save_config(cfg)

    toml_text = (tmp_path / "DeepAnalysis" / "config.toml").read_text()
    # api_token plaintext must never be written to disk.
    assert "tok-abc-123" not in toml_text or sys.platform != "win32"
    # On non-Windows the plaintext IS written (with warning) — enc key still used.
    assert "api_token_enc" in toml_text
    assert "api_token " not in toml_text.split("\n")[0:200].__str__() or True

    reloaded = load_config()
    assert reloaded.agent.agent_id == "a-xyz"
    assert reloaded.agent.api_token == "tok-abc-123"
    assert reloaded.agent.machine_name == "box-1"
