"""MCP tool registration.

The SDK's ``Server`` instance permits only one ``@server.list_tools()`` and
one ``@server.call_tool()`` handler. Each tool group exposes a registry of
``{name: (Tool, async-handler)}`` rather than installing its own decorators,
and ``register_all`` composes those registries into a single dispatch pair
so every group ships under the same server without clobbering siblings.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp import types
from mcp.server import Server

from . import analytics as analytics_tools
from . import issues as issue_tools
from . import projects as project_tools
from . import sprints as sprint_tools
from . import users as user_tools

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ToolEntry = tuple[types.Tool, ToolHandler]


def register_all(
    server: Server,
    *,
    issue_ctx: issue_tools.IssueToolContext,
    analytics_ctx: analytics_tools.AnalyticsToolContext,
    sprint_ctx: sprint_tools.SprintToolContext,
    project_client: project_tools.ProjectClient,
    user_client: user_tools.UserClient,
) -> dict[str, ToolEntry]:
    """Compose every tool group into one ``list_tools`` / ``call_tool`` pair.

    Args:
        server: The MCP server to attach handlers to.
        issue_ctx: Issue tool dependencies.
        analytics_ctx: Analytics tool dependencies.
        sprint_ctx: Sprint tool dependencies.
        project_client: Project client (read-only tools).
        user_client: User client (read-only tools).

    Returns:
        The merged registry. Mostly returned for tests; the side effect
        (registering the SDK handlers) is what production code relies on.

    Raises:
        ValueError: When two groups expose the same tool name. That would
            silently overwrite one group's behaviour, so we fail loud.
    """
    merged: dict[str, ToolEntry] = {}
    for group_name, entries in (
        ("issues", issue_tools.register(server, issue_ctx)),
        ("analytics", analytics_tools.register(server, analytics_ctx)),
        ("sprints", sprint_tools.register(server, sprint_ctx)),
        ("projects", project_tools.register(server, project_client)),
        ("users", user_tools.register(server, user_client)),
    ):
        for name, entry in entries.items():
            if name in merged:
                msg = f"tool name collision on {name!r} (second hit from {group_name})"
                raise ValueError(msg)
            merged[name] = entry

    tool_defs = [tool for tool, _handler in merged.values()]

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return tool_defs

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            _, handler = merged[name]
        except KeyError as exc:
            raise ValueError(f"unknown tool: {name}") from exc
        return await handler(arguments)

    # The decorators install the handlers as a side effect. We hold the
    # references so static analysers do not flag them as unused locals.
    _ = _list_tools
    _ = _call_tool

    return merged


__all__ = ["ToolEntry", "ToolHandler", "register_all"]
