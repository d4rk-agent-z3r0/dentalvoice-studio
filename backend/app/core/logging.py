# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Structured JSON logging with request/conversation correlation and redaction.

Both structlog events and stdlib records (uvicorn, SQLAlchemy, asyncpg) go through the same
processor chain, so every line on stdout is JSON and passes the same redaction step.
"""

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

REDACTED = "[REDACTED]"

# A key is sensitive if any of its word parts (split on _ - . and spaces) is in this set...
_SENSITIVE_PARTS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "authorization",
        "ticket",
        "cookie",
        "email",
        "phone",
        "dsn",
        "credential",
        "credentials",
    }
)
# ...or its normalised form contains one of these.
_SENSITIVE_SUBSTRINGS = ("api_key", "apikey", "database_url")
_PART_SPLIT = re.compile(r"[_\-.\s]+")

# Never emitted: prints full URLs including query strings (where WebSocket tickets travel).
# RequestIdMiddleware logs method, path and status instead.
_SUPPRESSED_LOGGERS = ("uvicorn.access",)


def _is_sensitive(key: str) -> bool:
    normalised = key.lower().replace("-", "_")
    if any(fragment in normalised for fragment in _SENSITIVE_SUBSTRINGS):
        return True
    return any(part in _SENSITIVE_PARTS for part in _PART_SPLIT.split(normalised))


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            k: REDACTED if isinstance(k, str) and _is_sensitive(k) else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value


# Query-string credentials inside free-text messages written by libraries (uvicorn logs the full
# WebSocket path, including ``?ticket=``, when it accepts a connection).
_QUERY_SECRET = re.compile(r"(?i)\b(ticket|token|access_token|key|api_key)=[^\s&\"']+")


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Redact sensitive keys at any depth, and credential-looking query parameters inside the
    event message. Our own code never puts sensitive values into messages; libraries can."""
    for key in list(event_dict):
        if key == "event":
            if isinstance(event_dict[key], str):
                event_dict[key] = _QUERY_SECRET.sub(rf"\1={REDACTED}", event_dict[key])
            continue
        event_dict[key] = REDACTED if _is_sensitive(key) else _redact(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    numeric_level = logging.getLevelNamesMapping()[level.upper()]
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        cache_logger_on_first_use=False,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            redact_sensitive,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric_level)

    # Uvicorn installs its own plain-text handlers before the app factory runs; route its loggers
    # through the root JSON handler instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    for name in _SUPPRESSED_LOGGERS:
        logging.getLogger(name).disabled = True


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger
