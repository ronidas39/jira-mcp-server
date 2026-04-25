"""Unit tests for the Jira MCP resource handlers.

These tests skip the MCP wire protocol entirely. They build a tiny ctx
object carrying only the ``jira_client`` fixture and call the resource
handler module directly. The goal is to verify URI parsing, REST path
selection, and JSON serialization of the response.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jira_mcp.clients.jira import JiraClient
from jira_mcp.resources.jira_resources import read_resource


@pytest.fixture
def ctx(jira_client: JiraClient) -> SimpleNamespace:
    """Minimal ServerContext-shaped object for resource tests."""
    return SimpleNamespace(jira_client=jira_client)


async def test_issue_resource_returns_full_issue_json(ctx: SimpleNamespace) -> None:
    """``jira://issue/PROJ-123`` returns Issue JSON with key and summary."""
    result = await read_resource(ctx.jira_client, "jira://issue/PROJ-123")
    assert result.mime_type == "application/json"
    assert isinstance(result.content, str)
    body = json.loads(result.content)
    assert body["key"] == "PROJ-123"
    assert body["summary"] == "Persist sprint metadata to MongoDB on every poll"


async def test_project_resource_returns_project_json(ctx: SimpleNamespace) -> None:
    """``jira://project/PROJ`` returns the project's name from the fixture."""
    result = await read_resource(ctx.jira_client, "jira://project/PROJ")
    assert result.mime_type == "application/json"
    body = json.loads(result.content)
    assert body["key"] == "PROJ"
    assert body["name"] == "Platform"


async def test_sprint_resource_returns_sprint_json(ctx: SimpleNamespace) -> None:
    """``jira://sprint/42`` returns sprint id 42 from the fixture."""
    result = await read_resource(ctx.jira_client, "jira://sprint/42")
    assert result.mime_type == "application/json"
    body = json.loads(result.content)
    assert body["id"] == 42
    assert body["state"] == "active"


async def test_unknown_scheme_is_rejected(ctx: SimpleNamespace) -> None:
    """A non-jira:// URI is rejected with a clear ValueError."""
    with pytest.raises(ValueError, match="scheme"):
        await read_resource(ctx.jira_client, "http://example.com/foo")


async def test_search_requires_jql(ctx: SimpleNamespace) -> None:
    """``jira://search`` without a ``jql`` query parameter is a ValueError."""
    with pytest.raises(ValueError, match="jql"):
        await read_resource(ctx.jira_client, "jira://search")
