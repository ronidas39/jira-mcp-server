"""Async retry policy for Jira API calls.

Jira Cloud rate-limits aggressively (a 429 with a ``Retry-After`` header is
the normal back-pressure signal) and occasionally returns a 5xx during
deploys. Both are transient, so the right behavior is exponential backoff
with a jitter and a small retry cap, rather than failing the tool call back
to the model.

The decorator is async-only because every code path that talks to Jira is
async; bringing in the sync variants would just add surface area no one will
use.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .errors import RateLimitError, UpstreamError

P = ParamSpec("P")
R = TypeVar("R")

# Tunables. Kept module-level so test code can monkeypatch them per-test
# rather than having to rebuild the decorator.
MAX_ATTEMPTS = 3
INITIAL_WAIT_SECONDS = 1.0
WAIT_MULTIPLIER = 2.0
MAX_WAIT_SECONDS = 30.0


def retry_jira_request(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Wrap an async Jira call with retry-on-transient-error semantics.

    The retry budget is intentionally small. Three attempts with exponential
    backoff capped at 30 seconds keeps the worst-case tool latency below a
    minute, which matters because MCP clients surface latency directly to
    the user. Anything beyond that is better handled by surfacing the error
    so the caller can decide.

    Only ``RateLimitError`` and ``UpstreamError`` are retried. Authentication
    failures, validation errors, and 4xx responses other than 429 are
    deterministic and would just burn time if retried.

    Args:
        func: An async function or method whose failures should be retried.

    Returns:
        A wrapped async callable with the same signature as ``func``.
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        retrying = AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=wait_exponential(
                multiplier=INITIAL_WAIT_SECONDS,
                exp_base=WAIT_MULTIPLIER,
                max=MAX_WAIT_SECONDS,
            ),
            retry=retry_if_exception_type((RateLimitError, UpstreamError)),
        )
        async for attempt in retrying:
            with attempt:
                result = await func(*args, **kwargs)
                # Tenacity needs the value set on the attempt's outcome to
                # treat it as the successful return; without this the loop
                # would keep retrying even on success.
                attempt.retry_state.set_result(result)
                return result
        # Unreachable: ``reraise=True`` guarantees the loop either returns
        # or propagates the last exception. Cast satisfies mypy --strict.
        return cast(R, None)

    return wrapper


__all__ = ["retry_jira_request"]


# Suppress unused-import warnings from typing helpers that mypy strict mode
# considers part of the public surface.
_ = Any
