"""Transport selection and serve loop.

Two transports are supported by the MCP spec for this server: stdio (the
canonical local transport, used by every MCP-capable IDE assistant) and
streamable HTTP (used when the server runs behind a reverse proxy and
clients connect over the network).

The stdio path uses the SDK's `stdio_server` async context manager, which
yields a pair of memory streams the low-level `Server.run` consumes.

The streamable HTTP path requires an ASGI host (uvicorn or similar) plus a
request-routed `StreamableHTTPServerTransport`. Wiring that cleanly is more
than a few lines and is out of scope for this milestone, so we raise
`NotImplementedError` with a pointer to the milestone that adds it.
"""

from __future__ import annotations

from ..config.settings import Settings
from ..utils.logging import get_logger
from .app import ServerContext

_log = get_logger("jira_mcp.server.transport")


async def _run_stdio(ctx: ServerContext) -> None:
    """Serve the MCP `Server` over stdio until stdin closes.

    The SDK's `stdio_server()` is an async context manager that wraps the
    process stdin and stdout in memory streams; `Server.run` consumes those
    streams and dispatches MCP requests until the peer disconnects.
    """
    from mcp.server.stdio import stdio_server  # noqa: PLC0415  (transport-local)

    init_options = ctx.server.create_initialization_options()
    _log.info("transport.stdio.start")
    async with stdio_server() as (read_stream, write_stream):
        await ctx.server.run(read_stream, write_stream, init_options)
    _log.info("transport.stdio.stop")


async def run(ctx: ServerContext, settings: Settings) -> None:
    """Run the MCP server against the configured transport.

    Args:
        ctx: The composed server context from `create_app`.
        settings: Validated runtime configuration; selects the transport.

    Raises:
        NotImplementedError: When `settings.mcp_transport == "http"`. The
            streamable HTTP transport needs an ASGI host and lifecycle
            wiring that lands in a follow-up milestone.
        ValueError: When `settings.mcp_transport` is an unknown value.
    """
    if settings.mcp_transport == "stdio":
        await _run_stdio(ctx)
        return
    if settings.mcp_transport == "http":
        msg = (
            "streamable HTTP transport is not wired yet; bind "
            f"({settings.mcp_http_host}:{settings.mcp_http_port}) lands in "
            "a follow-up milestone. Use MCP_TRANSPORT=stdio for now."
        )
        raise NotImplementedError(msg)
    msg = f"unsupported MCP_TRANSPORT: {settings.mcp_transport!r}"
    raise ValueError(msg)


__all__ = ["run"]
