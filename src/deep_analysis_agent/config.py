"""Agent configuration — Pydantic v2 settings backed by a TOML file.

Config file lives at `%LOCALAPPDATA%\\DeepAnalysis\\config.toml`.
Environment overrides use the `DEEP_ANALYSIS_` prefix and `__` as the
nested delimiter, e.g. `DEEP_ANALYSIS_MTGO__LOG_DIR=/tmp/x`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import TomlConfigSettingsSource

from .paths import app_data_dir, config_path


class MTGOSettings(BaseModel):
    log_dir: Path = Path("C:/Users/Default/AppData/Local/Apps/2.0")
    watched_suffixes: list[str] = Field(default_factory=lambda: [".dat", ".log"])
    stability_seconds: float = 5.0


class ServerSettings(BaseModel):
    url: str = "https://deepanalysis.sentania.net"
    tls_verify: bool | str = True


class AgentSettings(BaseModel):
    machine_name: str = ""
    # TODO(W8b): agent_id, api_token (DPAPI-protected) fields go here


class LoggingSettings(BaseModel):
    level: str = "INFO"
    log_dir: Path | None = None
    stderr: bool = True


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEEP_ANALYSIS_",
        env_nested_delimiter="__",
        toml_file=str(config_path()),
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
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def load_config(**overrides: Any) -> AppConfig:
    """Load config; create the app data dir on first call if missing."""
    app_data_dir().mkdir(parents=True, exist_ok=True)
    return AppConfig(**overrides)
