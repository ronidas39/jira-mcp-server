"""MCP resource handlers backed by the Jira REST API.

Four URI templates are exposed:

* ``jira://issue/{key}`` returns a fully expanded issue payload.
* ``jira://sprint/{id}`` returns sprint metadata from the Agile API.
* ``jira://project/{key}`` returns project metadata with issue types.
* ``jira://search?jql=<jql>`` runs a JQL search and returns the raw page.

The module talks to ``ServerContext.jira_client`` directly (rather than the
domain client wrappers under ``clients/``) so it stays decoupled from the
issue/sprint/project client modules that ship in parallel. That keeps each
subsystem testable on its own.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import ResourceTemplate
from pydantic import AnyUrl

from ..models.jira_entities import Issue, Project, Sprint

_JSON_MIME = "application/json"
_ISSUE_EXPAND = "renderedFields,transitions,changelog"
_SEARCH_MAX_RESULTS = 50


def _resource_templates() -> list[ResourceTemplate]:
    """Return the static list of URI templates this server publishes.

    Listed as ``ResourceTemplate`` (not ``Resource``) because each URI takes
    a parameter; clients use ``resources/templates/list`` to discover these.
    """
    return [
        ResourceTemplate(
            uriTemplate="jira://issue/{key}",
            name="jira-issue",
            description=(
                "Full Jira issue addressed by key (e.g. PROJ-123). Includes "
                "summary, status, assignee, comments, and available transitions."
            ),
            mimeType=_JSON_MIME,
        ),
        ResourceTemplate(
            uriTemplate="jira://sprint/{id}",
            name="jira-sprint",
            description=(
                "Agile sprint metadata addressed by numeric sprint id. "
                "Includes name, state, start/end dates, and goal."
            ),
            mimeType=_JSON_MIME,
        ),
        ResourceTemplate(
            uriTemplate="jira://project/{key}",
            name="jira-project",
            description=(
                "Jira project addressed by key (e.g. PROJ). Includes lead, "
                "description, and the list of issue types defined on it."
            ),
            mimeType=_JSON_MIME,
        ),
        ResourceTemplate(
            uriTemplate="jira://search?jql={jql}",
            name="jira-search",
            description=(
                "Run a JQL query and return the first page of results "
                f"(maxResults={_SEARCH_MAX_RESULTS})."
            ),
            mimeType=_JSON_MIME,
        ),
    ]


def _parse_uri(uri: str) -> tuple[str, str, dict[str, list[str]]]:
    """Split a ``jira://`` URI into (kind, tail, query).

    ``urlsplit`` is used rather than a hand-written regex because Jira keys
    can contain characters (digits, dashes) that would force escaping in a
    custom pattern, and ``urlsplit`` also handles the search query case.
    """
    parts = urlsplit(uri)
    if parts.scheme != "jira":
        msg = f"unsupported URI scheme: {parts.scheme!r}"
        raise ValueError(msg)
    kind = parts.netloc or parts.path.lstrip("/").split("/", 1)[0]
    # netloc holds the kind ("issue", "sprint", ...); the path holds the id.
    tail = parts.path.lstrip("/")
    query = parse_qs(parts.query)
    return kind, tail, query


async def _read_issue(jira_client: Any, key: str) -> str:
    """Fetch ``GET /rest/api/3/issue/{key}`` and return Issue JSON."""
    raw = await jira_client.get(
        f"/rest/api/3/issue/{key}",
        params={"expand": _ISSUE_EXPAND},
    )
    return Issue.from_api(raw).model_dump_json()


async def _read_sprint(jira_client: Any, sprint_id: str) -> str:
    """Fetch ``GET /rest/agile/1.0/sprint/{id}`` and return Sprint JSON."""
    raw = await jira_client.get(f"/rest/agile/1.0/sprint/{sprint_id}")
    return Sprint.model_validate(raw).model_dump_json()


async def _read_project(jira_client: Any, key: str) -> str:
    """Fetch ``GET /rest/api/3/project/{key}`` and return Project JSON."""
    raw = await jira_client.get(
        f"/rest/api/3/project/{key}",
        params={"expand": "issueTypes"},
    )
    return Project.model_validate(raw).model_dump_json()


async def _read_search(jira_client: Any, jql: str) -> str:
    """Run a JQL search and return the raw page JSON."""
    raw = await jira_client.get(
        "/rest/api/3/search",
        params={"jql": jql, "maxResults": _SEARCH_MAX_RESULTS},
    )
    # The raw search payload is already JSON-shaped; we serialize via
    # Issue/Project/Sprint elsewhere, but search results can contain custom
    # fields callers want to inspect, so we return them untouched.
    return json.dumps(raw)


async def read_resource(jira_client: Any, uri: str) -> ReadResourceContents:
    """Dispatch a ``jira://`` URI to the matching handler.

    Args:
        jira_client: The shared async Jira HTTP client.
        uri: The resource URI requested by the MCP client.

    Returns:
        A ``ReadResourceContents`` carrying JSON text and the JSON mime type.

    Raises:
        ValueError: When the URI does not match a known template or required
            query parameters are missing.
    """
    kind, tail, query = _parse_uri(uri)
    if kind == "issue":
        if not tail:
            msg = "jira://issue/{key} requires a key"
            raise ValueError(msg)
        body = await _read_issue(jira_client, tail)
    elif kind == "sprint":
        if not tail:
            msg = "jira://sprint/{id} requires a sprint id"
            raise ValueError(msg)
        body = await _read_sprint(jira_client, tail)
    elif kind == "project":
        if not tail:
            msg = "jira://project/{key} requires a project key"
            raise ValueError(msg)
        body = await _read_project(jira_client, tail)
    elif kind == "search":
        jql_values = query.get("jql") or []
        if not jql_values:
            msg = "jira://search requires a jql query parameter"
            raise ValueError(msg)
        body = await _read_search(jira_client, jql_values[0])
    else:
        msg = f"unknown jira resource kind: {kind!r}"
        raise ValueError(msg)
    return ReadResourceContents(content=body, mime_type=_JSON_MIME)


def register(server: Server, ctx: Any) -> None:
    """Wire resource handlers onto the MCP ``Server`` instance.

    Args:
        server: The MCP server to register handlers on.
        ctx: The server context; only ``ctx.jira_client`` is used here.
    """
    jira_client = ctx.jira_client

    @server.list_resource_templates()
    async def _list_templates() -> list[ResourceTemplate]:
        """Advertise the four jira:// URI templates served by this module."""
        return _resource_templates()

    @server.list_resources()
    async def _list_resources() -> list[Any]:
        """No fixed resource instances; everything is templated."""
        return []

    @server.read_resource()
    async def _read(uri: AnyUrl) -> list[ReadResourceContents]:
        """Resolve a single ``jira://`` URI to JSON text contents."""
        contents = await read_resource(jira_client, str(uri))
        return [contents]


__all__ = ["read_resource", "register"]
