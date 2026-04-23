"""structlog setup — JSON to a rotating file, optional stderr in dev."""

from __future__ import annotations

import logging
import logging.handlers
import sys

import structlog

from .config import AppConfig
from .paths import logs_dir

_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


def configure_logging(config: AppConfig) -> None:
    """Wire structlog + stdlib logging. Call once at startup."""
    log_dir = config.logging.log_dir or logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "agent.log"

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

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
