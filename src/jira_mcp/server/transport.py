"""Transport selection and serve loop.

Two transports are supported by the MCP spec for this server: stdio (the
canonical local transport, used by every MCP-capable IDE assistant) and
streamable HTTP (used when the server runs behind a reverse proxy, or when
a browser-based UI needs to talk to the server directly).

The stdio path uses the SDK's `stdio_server` async context manager, which
yields a pair of memory streams the low-level `Server.run` consumes.

The HTTP path mounts the SDK's `StreamableHTTPSessionManager` inside a
Starlette ASGI app and serves it with a programmatic `uvicorn.Server`. We
run uvicorn programmatically (rather than via `uvicorn.run`) so the serve
loop cooperates with the existing asyncio loop owned by `__main__`.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from ..config.settings import Settings
from ..utils.logging import get_logger
from .app import ServerContext

if TYPE_CHECKING:
    from starlette.applications import Starlette

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


def _cors_middleware(settings: Settings) -> list[object]:
    """Build the CORS middleware stack for the HTTP transport.

    Mcp-Session-Id is the spec-defined header that ties later requests to
    an existing session; it must be both accepted and exposed so a browser
    client can read it back from responses.
    """
    from starlette.middleware import Middleware  # noqa: PLC0415
    from starlette.middleware.cors import CORSMiddleware  # noqa: PLC0415

    return [
        Middleware(
            CORSMiddleware,
            allow_origins=list(settings.mcp_cors_origins),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Mcp-Session-Id", "Authorization"],
            expose_headers=["Mcp-Session-Id"],
        ),
    ]


def _build_http_app(ctx: ServerContext, settings: Settings) -> Starlette:
    """Build the Starlette ASGI app that hosts the streamable HTTP transport.

    The session manager is wired through Starlette's lifespan so its
    background task group starts before the first request and is cancelled
    cleanly on shutdown; the SDK requires this exact wiring (calling
    `manager.run()` outside a lifespan would skip its task-group setup).

    Args:
        ctx: The composed server context. Its `server` attribute is the
            low-level MCP `Server` instance the session manager dispatches
            to.
        settings: Validated runtime configuration. Provides the CORS origin
            allowlist the browser-side UI relies on.

    Returns:
        A Starlette app with the MCP endpoint mounted at `/mcp` and CORS
        middleware applied at the outer layer.
    """
    # Imports kept transport-local so stdio cold paths do not pull Starlette.
    from mcp.server.streamable_http_manager import (  # noqa: PLC0415
        StreamableHTTPSessionManager,
    )
    from starlette.applications import Starlette  # noqa: PLC0415
    from starlette.routing import Mount  # noqa: PLC0415
    from starlette.types import Receive, Scope, Send  # noqa: PLC0415

    session_manager = StreamableHTTPSessionManager(app=ctx.server)

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry that delegates to the session manager."""
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        """Run the session manager's task group for the app's lifetime."""
        async with session_manager.run():
            _log.info("transport.http.session_manager.started")
            try:
                yield
            finally:
                _log.info("transport.http.session_manager.stopping")

    # Mount at root and gate by path inside the handler. Mount("/mcp", ...)
    # 307-redirects /mcp to /mcp/, which most clients refuse to follow on a
    # POST and which adds an unnecessary round-trip even when they do.
    async def root(scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("path", "/").rstrip("/") == "/mcp":
            inner_scope = dict(scope)
            inner_scope["path"] = "/"
            inner_scope["raw_path"] = b"/"
            await handle_mcp(inner_scope, receive, send)
            return
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return Starlette(
        debug=False,
        routes=[Mount("/", app=root)],
        middleware=_cors_middleware(settings),  # type: ignore[arg-type]
        lifespan=lifespan,
    )


async def _run_http(ctx: ServerContext, settings: Settings) -> None:
    """Serve the MCP server over streamable HTTP via uvicorn.

    Uses `uvicorn.Server.serve()` rather than `uvicorn.run()` because we are
    already inside an asyncio loop owned by `__main__`, and `uvicorn.run`
    would try to start its own loop.
    """
    import uvicorn  # noqa: PLC0415  (transport-local)

    app = _build_http_app(ctx, settings)

    config = uvicorn.Config(
        app,
        host=settings.mcp_http_host,
        port=settings.mcp_http_port,
        log_level=settings.log_level.lower(),
        lifespan="on",
        access_log=False,
    )
    server = uvicorn.Server(config)

    _log.info(
        "transport.http.serving",
        host=settings.mcp_http_host,
        port=settings.mcp_http_port,
        origins=list(settings.mcp_cors_origins),
    )
    await server.serve()
    _log.info("transport.http.stopped")


async def run(ctx: ServerContext, settings: Settings) -> None:
    """Run the MCP server against the configured transport.

    Args:
        ctx: The composed server context from `create_app`.
        settings: Validated runtime configuration; selects the transport.

    Raises:
        ValueError: When `settings.mcp_transport` is an unknown value.
    """
    if settings.mcp_transport == "stdio":
        await _run_stdio(ctx)
        return
    if settings.mcp_transport == "http":
        await _run_http(ctx, settings)
        return
    msg = f"unsupported MCP_TRANSPORT: {settings.mcp_transport!r}"
    raise ValueError(msg)


__all__ = ["run"]
