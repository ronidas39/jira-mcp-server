"""Startup and shutdown hooks for the server.

These run outside the MCP transport's serve loop so connectivity failures
surface before a client ever connects: a process that cannot reach Jira or
Mongo should crash early with a structured event, not return cryptic errors
on the first tool call.
"""

from __future__ import annotations

from typing import Any

from ..utils.errors import JiraMcpError
from ..utils.logging import get_logger
from .app import ServerContext

_log = get_logger("jira_mcp.server.lifespan")


async def _check_jira(ctx: ServerContext) -> dict[str, Any]:
    """Hit Jira's `/myself` endpoint to confirm credentials and base URL.

    Done as a one-shot GET because the response is cheap and the only Jira
    endpoint guaranteed to be authorised for any token: it tells us both
    that the host resolves and that the credentials work in one round trip.
    """
    return await ctx.jira_client.get("/rest/api/3/myself")


async def startup(ctx: ServerContext) -> None:
    """Run startup checks: Mongo indexes, Mongo ping, Jira connectivity.

    Args:
        ctx: The composed server context returned from `create_app`.

    Raises:
        Exception: Any failure from Mongo or Jira is re-raised after a
            structured `*.connectivity.failed` event so the caller can log
            the startup.failed event and exit non-zero.
    """
    try:
        await ctx.audit.ensure_indexes()
        await ctx.mongo.ping()
        _log.info("mongo.connectivity.ok")
    except Exception as exc:
        _log.error("mongo.connectivity.failed", error=str(exc))
        raise

    try:
        me = await _check_jira(ctx)
        _log.info(
            "jira.connectivity.ok",
            display_name=me.get("displayName"),
            account_id=me.get("accountId"),
        )
    except JiraMcpError as exc:
        _log.error("jira.connectivity.failed", error=str(exc))
        raise
    except Exception as exc:
        _log.error("jira.connectivity.failed", error=str(exc))
        raise


async def shutdown(ctx: ServerContext) -> None:
    """Close shared HTTP and Mongo handles.

    Best-effort: each close is wrapped so a failure in one path does not
    prevent the other from running. A leaked socket on shutdown is worse
    than a noisy log line.
    """
    try:
        await ctx.http.aclose()
    except Exception as exc:
        _log.warning("http.close.failed", error=str(exc))

    try:
        await ctx.mongo.close()
    except Exception as exc:
        _log.warning("mongo.close.failed", error=str(exc))


__all__ = ["shutdown", "startup"]
