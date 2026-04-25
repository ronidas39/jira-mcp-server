"""Structured logging setup.

`structlog` with a JSON renderer is the production format. A small processor
runs before the renderer and replaces the value of any sensitive-looking key
(`Authorization`, `password`, `token`, `api_key`, `secret`) with `***`. This
catches the easy mistakes; tool authors should also avoid putting secrets in
log fields in the first place.

The configuration is idempotent so test fixtures can call it freely without
duplicating processors on every reconfigure.
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEYS = {"authorization", "password", "token", "api_key", "secret"}


def _scrub_sensitive(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: replace sensitive values with `***`."""
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog and the stdlib logging root. Idempotent."""
    logging.basicConfig(format="%(message)s", level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _scrub_sensitive,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a configured structlog logger."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
