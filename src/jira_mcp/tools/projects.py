"""MCP tools for the project domain.

Three read-only tools live here:

* ``list_projects``: enumerate every project the principal can browse.
* ``get_project``: fetch one project's metadata, including issue types and
  components.
* ``list_custom_fields``: enumerate tenant-defined custom fields.

Read-only tools do not write to the audit log on purpose: the audit chain is
about Jira mutations, not lookups, and recording every read would balloon
the collection without giving operators useful signal.

The registration surface mirrors the SDK's ``@server.list_tools`` and
``@server.call_tool`` pattern, but the SDK only allows a single handler for
each. To let multiple tool modules coexist, ``register`` returns a
name-keyed dispatch map; the server bootstrap merges every module's map and
installs single SDK-level handlers that route by tool name.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import mcp.types as mcp_types
from mcp.server import Server

from ..clients.projects import ProjectClient
from ..models.tool_io import (
    GetProjectInput,
    GetProjectOutput,
    ListCustomFieldsOutput,
    ListProjectsOutput,
)

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ToolEntry = tuple[mcp_types.Tool, ToolHandler]


def _build_handlers(client: ProjectClient) -> dict[str, ToolEntry]:
    """Construct ``Tool`` definitions and async dispatchers.

    Returns:
        Map from tool name to a ``(Tool, handler)`` tuple. Handler accepts
        the raw arguments dict from the SDK and returns a JSON-ready dict.
    """

    async def list_projects_handler(_args: dict[str, Any]) -> dict[str, Any]:
        projects = await client.list_projects()
        return ListProjectsOutput(projects=projects).model_dump(mode="json", by_alias=True)

    async def get_project_handler(args: dict[str, Any]) -> dict[str, Any]:
        params = GetProjectInput.model_validate(args)
        project = await client.get(params.key_or_id)
        return GetProjectOutput(project=project).model_dump(mode="json", by_alias=True)

    async def list_custom_fields_handler(_args: dict[str, Any]) -> dict[str, Any]:
        result = await client.list_custom_fields()
        return result.model_dump(mode="json", by_alias=True)

    return {
        "list_projects": (
            mcp_types.Tool(
                name="list_projects",
                description=(
                    "List every Jira project the authenticated principal can "
                    "browse. Use this when the caller asks 'what projects do "
                    "I have' or needs a project key for a follow-up call. "
                    "Returns project keys, names, and lead users; does not "
                    "include issue types (use get_project for that)."
                ),
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
                outputSchema=ListProjectsOutput.model_json_schema(),
            ),
            list_projects_handler,
        ),
        "get_project": (
            mcp_types.Tool(
                name="get_project",
                description=(
                    "Fetch metadata for a single Jira project by key or "
                    "numeric id. Use this when the caller needs the project "
                    "lead, description, or to discover which issue types and "
                    "components the project supports before creating an "
                    "issue. Prefer this over list_projects when a specific "
                    "project is already known."
                ),
                inputSchema=GetProjectInput.model_json_schema(),
                outputSchema=GetProjectOutput.model_json_schema(),
            ),
            get_project_handler,
        ),
        "list_custom_fields": (
            mcp_types.Tool(
                name="list_custom_fields",
                description=(
                    "List every tenant-defined Jira custom field with its "
                    "id and human-readable name. Use this before calling "
                    "create_issue or update_issue when the caller refers to "
                    "a field by name (for example 'Story Points') so you "
                    "can map the name to its ``customfield_*`` id. Read-only."
                ),
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
                outputSchema=ListCustomFieldsOutput.model_json_schema(),
            ),
            list_custom_fields_handler,
        ),
    }


def register(server: Server, client: ProjectClient) -> dict[str, ToolEntry]:
    """Build and return the project tool registry for this server.

    The MCP SDK supports a single ``@server.list_tools`` and
    ``@server.call_tool`` handler per ``Server`` instance, so per-module
    registration cannot install its own decorators without clobbering other
    groups. We return the registry instead and let the bootstrap compose
    the global handlers from every group's map.

    Args:
        server: The MCP server instance. Currently unused at the module
            level; accepted for signature parity with the other tool groups
            so the bootstrap can call them uniformly.
        client: A configured :class:`ProjectClient`.

    Returns:
        Map from tool name to ``(Tool, handler)``.
    """
    del server  # Kept in the signature for uniform bootstrap wiring.
    return _build_handlers(client)


__all__ = ["ToolEntry", "ToolHandler", "register"]
