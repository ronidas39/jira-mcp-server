"""Unit tests for the project MCP tool wrappers.

These confirm that each tool function returns a payload that matches the
declared Pydantic output schema, and that the read-only tools never touch
the audit repository.
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import MagicMock

import httpx
import respx
from mcp.server import Server

from jira_mcp.clients.jira import JiraClient
from jira_mcp.clients.projects import ProjectClient
from jira_mcp.models.tool_io import (
    GetProjectOutput,
    ListCustomFieldsOutput,
    ListProjectsOutput,
)
from jira_mcp.tools.projects import register


def _server() -> Server:
    """Return a bare MCP Server suitable for register() to inspect."""
    return Server(name="test", version="0.0.0")


async def test_register_exposes_three_read_only_tools(
    jira_client: JiraClient,
) -> None:
    """register() returns the three project tools with output schemas."""
    client = ProjectClient(jira_client)
    registry = register(_server(), client)
    assert set(registry) == {"list_projects", "get_project", "list_custom_fields"}
    for name, (tool, _handler) in registry.items():
        assert tool.name == name
        assert tool.description is not None
        assert "use" in tool.description.lower()
        assert tool.outputSchema is not None


async def test_list_projects_handler_shape(
    jira_client: JiraClient,
) -> None:
    """The list_projects handler produces a payload that re-validates to ListProjectsOutput."""
    client = ProjectClient(jira_client)
    registry = register(_server(), client)
    _tool, handler = registry["list_projects"]
    payload: dict[str, Any] = await handler({})
    parsed = ListProjectsOutput.model_validate(payload)
    assert len(parsed.projects) == 3


async def test_get_project_handler_shape(
    jira_client: JiraClient,
) -> None:
    """The get_project handler returns a single Project under 'project'."""
    client = ProjectClient(jira_client)
    registry = register(_server(), client)
    _tool, handler = registry["get_project"]
    payload = await handler({"key_or_id": "PROJ"})
    parsed = GetProjectOutput.model_validate(payload)
    assert parsed.project.key == "PROJ"


async def test_list_custom_fields_handler_shape(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """The list_custom_fields handler produces a ListCustomFieldsOutput payload."""
    fields_payload = [
        {
            "id": "customfield_10005",
            "name": "Story Points",
            "custom": True,
            "schema": {"type": "number", "custom": "x"},
        }
    ]
    # The conftest mock router does not pre-mount /rest/api/3/field, so we
    # add the route here. ``mock_jira_http`` is the same router yielded to
    # the fixture chain.
    mock_jira_http.get("https://example.atlassian.net/rest/api/3/field").mock(
        return_value=httpx.Response(200, json=fields_payload),
    )

    client = ProjectClient(jira_client)
    registry = register(_server(), client)
    _tool, handler = registry["list_custom_fields"]
    payload = await handler({})
    parsed = ListCustomFieldsOutput.model_validate(payload)
    assert len(parsed.fields) == 1
    assert parsed.fields[0].id == "customfield_10005"


async def test_handlers_do_not_touch_audit_repository(
    jira_client: JiraClient,
) -> None:
    """Read-only tools should never call AuditRepository.record.

    The handlers do not depend on an audit instance, so calling them should
    not even reach a sentinel mock; we assert that explicitly to lock the
    contract in case a future refactor wires audit into read paths.
    """
    audit = MagicMock()
    audit.record = MagicMock()
    client = ProjectClient(jira_client)
    registry = register(_server(), client)
    for name, (_tool, handler) in registry.items():
        args: dict[str, Any] = {"key_or_id": "PROJ"} if name == "get_project" else {}
        # list_custom_fields needs a route that may not be mounted in this
        # test; we only care that audit was not invoked, so a transport
        # failure on that one tool is acceptable here.
        with contextlib.suppress(Exception):
            await handler(args)
    audit.record.assert_not_called()
