"""Agent configuration — Pydantic v2 settings backed by a TOML file.

Config file lives at `%LOCALAPPDATA%\\DeepAnalysis\\config.toml`.
Environment overrides use the `DEEP_ANALYSIS_` prefix and `__` as the
nested delimiter, e.g. `DEEP_ANALYSIS_MTGO__LOG_DIR=/tmp/x`.

Token storage: `api_token` is held in memory on `AgentSettings`, but
persisted to TOML as a DPAPI-encrypted blob under the key
`api_token_enc`. The plaintext `api_token` is never written to disk.
"""

from __future__ import annotations

import base64
import logging
import os
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import TomlConfigSettingsSource

from .paths import app_data_dir, config_path

logger = logging.getLogger(__name__)

try:  # pragma: no cover — Windows only
    import win32crypt

    _DPAPI = True
except ImportError:  # pragma: no cover — non-Windows CI path
    win32crypt = None
    _DPAPI = False


def _default_mtgo_log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Apps" / "2.0"
    return Path.home() / "AppData" / "Local" / "Apps" / "2.0"


class MTGOSettings(BaseModel):
    log_dir: Path = Field(default_factory=_default_mtgo_log_dir)
    watched_suffixes: list[str] = Field(default_factory=lambda: [".dat", ".log"])
    stability_seconds: float = 5.0


class ServerSettings(BaseModel):
    url: str = "https://deepanalysis.sentania.net"
    tls_verify: bool | str = True


class AgentSettings(BaseModel):
    machine_name: str = ""
    agent_id: str | None = None
    api_token: str | None = None
    registered_at: datetime | None = None
    heartbeat_interval_seconds: int = 300


class LoggingSettings(BaseModel):
    level: str = "INFO"
    log_dir: Path | None = None
    stderr: bool = True


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEEP_ANALYSIS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    mtgo: MTGOSettings = Field(default_factory=MTGOSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml_source = TomlConfigSettingsSource(settings_cls, toml_file=config_path())
        return (
            init_settings,
            env_settings,
            toml_source,
            file_secret_settings,
        )


def encrypt_token(token: str) -> str:
    """Encrypt a token via Windows DPAPI. No-op (identity) off-Windows."""
    if not _DPAPI or sys.platform != "win32":
        logger.warning("api_token stored in plaintext (DPAPI unavailable on %s)", sys.platform)
        return token
    blob = win32crypt.CryptProtectData(token.encode("utf-8"), "DeepAnalysis", None, None, None, 0)
    return base64.b64encode(blob).decode("ascii")


def decrypt_token(blob: str) -> str:
    """Decrypt a DPAPI blob. No-op (identity) off-Windows."""
    if not _DPAPI or sys.platform != "win32":
        return blob
    raw = base64.b64decode(blob.encode("ascii"))
    _desc, data = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
    return str(data.decode("utf-8"))


def _config_to_toml(config: AppConfig) -> str:
    """Serialize AppConfig to a TOML string, DPAPI-wrapping the api_token."""
    lines: list[str] = []

    def _render_value(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int | float):
            return str(v)
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, list):
            return "[" + ", ".join(_render_value(x) for x in v) + "]"
        # Strings and paths — escape backslashes and quotes.
        s = str(v).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'

    def _section(name: str, data: dict[str, Any]) -> None:
        if not data:
            return
        lines.append(f"[{name}]")
        for key, val in data.items():
            if val is None:
                continue
            lines.append(f"{key} = {_render_value(val)}")
        lines.append("")

    _section("mtgo", config.mtgo.model_dump(mode="python"))
    _section("server", config.server.model_dump(mode="python"))

    agent_data = config.agent.model_dump(mode="python")
    token = agent_data.pop("api_token", None)
    if token:
        agent_data["api_token_enc"] = encrypt_token(token)
    _section("agent", agent_data)

    logging_data = config.logging.model_dump(mode="python")
    _section("logging", logging_data)

    return "\n".join(lines).rstrip() + "\n"


def save_config(config: AppConfig) -> None:
    """Write config to TOML atomically (write to .tmp then os.replace)."""
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(_config_to_toml(config), encoding="utf-8")
    os.replace(tmp, target)


def load_config(**overrides: Any) -> AppConfig:
    """Load config; create the app data dir on first call if missing.

    If the TOML contains `api_token_enc`, decrypt it into the in-memory
    `agent.api_token` field so callers can use it directly.
    """
    app_data_dir().mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(**overrides)

    target = config_path()
    if target.is_file():
        try:
            raw = tomllib.loads(target.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            logger.warning("failed to re-read TOML for api_token_enc", exc_info=True)
            return cfg
        enc = raw.get("agent", {}).get("api_token_enc")
        if enc and not cfg.agent.api_token:
            try:
                cfg.agent.api_token = decrypt_token(enc)
            except Exception:
                logger.exception("failed to decrypt api_token_enc — re-registration required")
                cfg.agent.api_token = None
    return cfg
