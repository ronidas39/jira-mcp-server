"""Unit tests for the user MCP tool wrappers.

Confirms that each tool function returns a payload matching its Pydantic
output schema and that the read-only tools never touch the audit repository.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import respx
from mcp.server import Server

from jira_mcp.clients.jira import JiraClient
from jira_mcp.clients.users import UserClient
from jira_mcp.models.tool_io import ListUsersOutput, ResolveUserOutput
from jira_mcp.tools.users import register

JIRA_BASE_URL = "https://example.atlassian.net"


def _server() -> Server:
    """Return a bare MCP Server suitable for register() to inspect."""
    return Server(name="test", version="0.0.0")


async def test_register_exposes_two_read_only_tools(
    jira_client: JiraClient,
) -> None:
    """register() returns the two user tools with output schemas attached."""
    client = UserClient(jira_client)
    registry = register(_server(), client)
    assert set(registry) == {"list_users", "resolve_user"}
    for name, (tool, _handler) in registry.items():
        assert tool.name == name
        assert tool.description is not None
        assert "use" in tool.description.lower()
        assert tool.outputSchema is not None


async def test_list_users_handler_returns_directory(
    jira_client: JiraClient,
) -> None:
    """The list_users handler produces a ListUsersOutput payload."""
    client = UserClient(jira_client)
    registry = register(_server(), client)
    _tool, handler = registry["list_users"]
    payload: dict[str, Any] = await handler({"max_results": 50})
    parsed = ListUsersOutput.model_validate(payload)
    assert len(parsed.users) == 2


async def test_list_users_handler_caps_results(
    jira_client: JiraClient,
) -> None:
    """max_results bounds the returned list even when Jira returns more."""
    client = UserClient(jira_client)
    registry = register(_server(), client)
    _tool, handler = registry["list_users"]
    payload = await handler({"max_results": 1})
    parsed = ListUsersOutput.model_validate(payload)
    assert len(parsed.users) == 1


async def test_resolve_user_handler_returns_match(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """The resolve_user handler returns a ResolveUserOutput with a populated user."""
    payload = [
        {
            "accountId": "557058:abc-1111",
            "displayName": "Alice Engineer",
            "emailAddress": "alice@example.com",
            "active": True,
        }
    ]
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/user/search").mock(
        return_value=httpx.Response(200, json=payload)
    )

    client = UserClient(jira_client)
    registry = register(_server(), client)
    _tool, handler = registry["resolve_user"]
    out = ResolveUserOutput.model_validate(await handler({"identifier": "alice@example.com"}))
    assert out.user is not None
    assert out.user.account_id == "557058:abc-1111"


async def test_resolve_user_handler_returns_null_on_ambiguous(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """Ambiguous matches surface as ``user: null`` to the model."""
    payload = [
        {
            "accountId": "557058:abc-1111",
            "displayName": "Alex Smith",
            "emailAddress": "alex.engineering@example.com",
            "active": True,
        },
        {
            "accountId": "557058:def-2222",
            "displayName": "Alex Smith",
            "emailAddress": "alex.product@example.com",
            "active": True,
        },
    ]
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/user/search").mock(
        return_value=httpx.Response(200, json=payload)
    )

    client = UserClient(jira_client)
    registry = register(_server(), client)
    _tool, handler = registry["resolve_user"]
    out = ResolveUserOutput.model_validate(await handler({"identifier": "Alex Smith"}))
    assert out.user is None


async def test_handlers_do_not_touch_audit_repository(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """Read-only tools should never call AuditRepository.record."""
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/user/search").mock(
        return_value=httpx.Response(200, json=[])
    )
    audit = MagicMock()
    audit.record = MagicMock()
    client = UserClient(jira_client)
    registry = register(_server(), client)
    for name, (_tool, handler) in registry.items():
        args: dict[str, Any] = (
            {"identifier": "nobody@example.com"} if name == "resolve_user" else {}
        )
        await handler(args)
    audit.record.assert_not_called()
