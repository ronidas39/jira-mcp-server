"""MCP tools for the user domain.

Two read-only tools live here:

* ``list_users``: substring-search the user directory, optionally restricted
  to users assignable to a project.
* ``resolve_user``: translate a human label (email or display name) into a
  unique :class:`User`. The resolver is conservative: ambiguous matches
  return ``None`` rather than guess; see :meth:`UserClient.resolve` for the
  exact policy.

Read-only tools do not write to the audit log because the audit chain is
about Jira mutations, not lookups.

The registration surface follows the same convention as the project tools:
``register`` returns a name-keyed dispatch map and the server bootstrap
combines every module's map into single SDK-level handlers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import mcp.types as mcp_types
from mcp.server import Server

from ..clients.users import UserClient
from ..models.tool_io import (
    ListUsersInput,
    ListUsersOutput,
    ResolveUserInput,
    ResolveUserOutput,
)

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ToolEntry = tuple[mcp_types.Tool, ToolHandler]


def _build_handlers(client: UserClient) -> dict[str, ToolEntry]:
    """Construct ``Tool`` definitions and async dispatchers.

    Returns:
        Map from tool name to a ``(Tool, handler)`` tuple. Handlers accept
        the raw arguments dict from the SDK and return a JSON-ready dict.
    """

    async def list_users_handler(args: dict[str, Any]) -> dict[str, Any]:
        params = ListUsersInput.model_validate(args)
        users = await client.list_users(query=params.query)
        # ``max_results`` is a client-side cap because the directory search
        # endpoint does not honour ``maxResults`` consistently across tenants.
        capped = users[: params.max_results]
        return ListUsersOutput(users=capped).model_dump(mode="json", by_alias=True)

    async def resolve_user_handler(args: dict[str, Any]) -> dict[str, Any]:
        params = ResolveUserInput.model_validate(args)
        user = await client.resolve(params.identifier)
        return ResolveUserOutput(user=user).model_dump(mode="json", by_alias=True)

    return {
        "list_users": (
            mcp_types.Tool(
                name="list_users",
                description=(
                    "Search the Jira user directory by substring against "
                    "display name and email. Use this when the caller wants "
                    "to browse users or pick from a short list; pass an "
                    "empty query to enumerate the first page. For "
                    "name-to-accountId resolution prefer resolve_user, "
                    "which is stricter about ambiguity."
                ),
                inputSchema=ListUsersInput.model_json_schema(),
                outputSchema=ListUsersOutput.model_json_schema(),
            ),
            list_users_handler,
        ),
        "resolve_user": (
            mcp_types.Tool(
                name="resolve_user",
                description=(
                    "Translate an email or display name into a unique Jira "
                    "user, returning null when the match is ambiguous or "
                    "absent. Use this before any tool that expects an "
                    "accountId, such as create_issue with assignee or "
                    "update_issue. The resolver prefers email matches when "
                    "the input contains '@'."
                ),
                inputSchema=ResolveUserInput.model_json_schema(),
                outputSchema=ResolveUserOutput.model_json_schema(),
            ),
            resolve_user_handler,
        ),
    }


def register(server: Server, client: UserClient) -> dict[str, ToolEntry]:
    """Build and return the user tool registry for this server.

    See :func:`jira_mcp.tools.projects.register` for the rationale behind
    returning a registry instead of installing SDK decorators directly.

    Args:
        server: The MCP server instance. Accepted for signature parity with
            the other tool groups; the bootstrap installs the merged
            registrations.
        client: A configured :class:`UserClient`.

    Returns:
        Map from tool name to ``(Tool, handler)``.
    """
    del server  # Kept in the signature for uniform bootstrap wiring.
    return _build_handlers(client)


__all__ = ["ToolEntry", "ToolHandler", "register"]
