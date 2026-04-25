"""Context variables for actor identity and correlation ids.

Why contextvars rather than threading.local: every request path is async, and
ContextVar is the only mechanism that survives task hops correctly inside an
asyncio loop. The audit layer reads these on every write tool call so each
log row is traceable back to the operator and to the originating request,
even when many tools run concurrently.

The actor variable defaults to the literal string ``"unknown"`` until the
auth context is wired; that way audit rows are still well-formed before the
authentication layer lands, and a future change does not require touching
every tool to start populating the field.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

# Default actor when no auth context has been bound. Kept as a module-level
# constant so tests can assert against it without re-typing the string.
DEFAULT_ACTOR = "unknown"

actor_var: ContextVar[str] = ContextVar("actor_var", default=DEFAULT_ACTOR)
"""Identity of the principal making the current call.

Bound by the auth middleware once that exists; until then every record
carries the default ``"unknown"`` value.
"""

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id_var", default=None)
"""Per-request correlation id, propagated across log lines and audit rows.

``None`` means "no caller-supplied id"; the helper below mints a fresh hex
uuid on demand so audit rows always have a value to record.
"""


def get_or_new_correlation_id() -> str:
    """Return the bound correlation id, or mint and return a new uuid4 hex.

    Returns:
        The current correlation id when one is bound on the context, or a
        fresh ``uuid.uuid4().hex`` otherwise. The helper does not mutate
        the contextvar; the caller is responsible for binding the value
        if downstream layers need to see the same id.
    """
    current = correlation_id_var.get()
    if current:
        return current
    return uuid.uuid4().hex


def get_actor() -> str:
    """Return the bound actor, falling back to the default sentinel."""
    return actor_var.get()


__all__ = [
    "DEFAULT_ACTOR",
    "actor_var",
    "correlation_id_var",
    "get_actor",
    "get_or_new_correlation_id",
]
