"""structlog setup — JSON or plaintext to a rotating file, optional stderr in dev."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog

from .config import AppConfig
from .paths import logs_dir

_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


def log_file_path(config: AppConfig) -> Path:
    """Return the active agent log file path."""
    base = config.logging.log_dir or logs_dir()
    return base / "agent.log"


def configure_logging(config: AppConfig) -> None:
    """Wire structlog + stdlib logging. Call once at startup."""
    log_file = log_file_path(config)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, config.logging.level.upper(), logging.INFO)

    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(
            log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
    ]
    if config.logging.stderr:
        handlers.append(logging.StreamHandler(sys.stderr))

    formatter = logging.Formatter("%(message)s")
    for h in handlers:
        h.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)

    # Quiet third-party loggers that emit pre-formatted strings (not structlog
    # events) and would otherwise pollute the JSON log with raw lines like
    # `HTTP Request: POST ... "HTTP/1.1 200 OK"`.
    for noisy in ("httpx", "httpcore", "hpack", "h2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if config.logging.format.lower() == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
