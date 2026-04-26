"""structlog setup — JSON or plaintext to a rotating file, optional stderr in dev."""

from __future__ import annotations

import datetime
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


class _ManalogStyleRenderer:
    """structlog processor that emits manalog-style human-readable lines.

    Format: ``YYYY-MM-DD HH:MM:SS,mmm LEVEL name: event k=v k=v``

    Key-value pairs (other than ``timestamp``/``level``/``event``) are
    sorted alphabetically and appended after the event slug. Exception
    tracebacks rendered by ``format_exc_info`` are appended on a
    trailing line.
    """

    def __call__(
        self,
        logger: Any,
        method_name: str,
        event_dict: dict[str, Any],
    ) -> str:
        # Drop any upstream timestamp — we compute our own in local time
        # with millisecond precision to match stdlib `asctime` formatting.
        event_dict.pop("timestamp", None)

        level = str(event_dict.pop("level", method_name)).upper()
        event = event_dict.pop("event", "")
        exception = event_dict.pop("exception", None)
        stack = event_dict.pop("stack", None)

        name = getattr(logger, "name", "") or ""

        now = datetime.datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S,") + f"{now.microsecond // 1000:03d}"

        kv = " ".join(f"{k}={event_dict[k]}" for k in sorted(event_dict))
        head = f"{ts} {level} {name}: {event}".rstrip()
        line = f"{head} {kv}" if kv else head
        if stack:
            line = f"{line}\n{stack}"
        if exception:
            line = f"{line}\n{exception}"
        return line


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

    is_json = config.logging.format.lower() == "json"

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if is_json:
        # JSON mode keeps an ISO UTC timestamp for machine consumers.
        processors.append(structlog.processors.TimeStamper(fmt="iso", utc=True))
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Plaintext mode: manalog-style line, renderer generates its own
        # local-time timestamp.
        processors.append(_ManalogStyleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
