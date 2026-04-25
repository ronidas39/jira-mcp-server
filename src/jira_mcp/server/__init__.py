"""MCP server package: app composition, transport, lifecycle hooks.

Re-exports the public surface so the entry point can compose the server
without reaching into submodules:

    from jira_mcp.server import ServerContext, create_app, run, startup, shutdown
"""

from __future__ import annotations

from .app import ServerContext, create_app, resolve_oauth_cloud_id
from .lifespan import shutdown, startup
from .transport import run

__all__ = [
    "ServerContext",
    "create_app",
    "resolve_oauth_cloud_id",
    "run",
    "shutdown",
    "startup",
]
