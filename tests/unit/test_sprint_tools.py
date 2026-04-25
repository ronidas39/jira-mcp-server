"""Unit tests for the sprint MCP tool dispatch.

Verifies two contracts:
    * ``move_to_sprint`` writes one well-formed audit row per call (FR-404,
      FR-901).
    * ``sprint_report`` returns a fully populated :class:`SprintReportOutput`
      payload (FR-405).
"""

from __future__ import annotations

from typing import Any

import httpx
import respx

from jira_mcp.clients.jira import JiraClient
from jira_mcp.clients.sprints import SprintClient
from jira_mcp.db.repositories.audit import AuditRepository
from jira_mcp.tools.sprints import SPRINT_TOOLS, build_sprint_dispatch

BASE_URL = "https://example.atlassian.net"


def test_sprint_tools_descriptor_set() -> None:
    """Sanity: every tool name the dispatcher needs is exported as a descriptor."""
    names = {tool.name for tool in SPRINT_TOOLS}
    assert names == {
        "list_boards",
        "list_sprints",
        "get_sprint",
        "move_to_sprint",
        "sprint_report",
    }


async def test_move_to_sprint_records_audit_row(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
    mock_mongo_db: Any,
) -> None:
    """FR-404 and FR-901: a successful move writes one ok-status audit row."""
    mock_jira_http.post(f"{BASE_URL}/rest/agile/1.0/sprint/42/issue").mock(
        return_value=httpx.Response(204)
    )
    sprint_client = SprintClient(jira_client)
    audit = AuditRepository(mock_mongo_db)
    dispatch = build_sprint_dispatch(sprint_client, audit)

    payload = {"sprint_id": 42, "issue_keys": ["PROJ-123", "PROJ-124"]}
    result = await dispatch["move_to_sprint"](payload)

    assert result == {"moved_count": 2}

    docs = [d async for d in mock_mongo_db["audit_log"].find({})]
    assert len(docs) == 1
    row = docs[0]
    assert row["tool"] == "move_to_sprint"
    assert row["response_status"] == "ok"
    assert row["jira_id"] == "42"
    assert row["input_summary"] == {
        "sprint_id": 42,
        "issue_keys": ["PROJ-123", "PROJ-124"],
    }
    # Hash is hex SHA-256, so 64 hex chars.
    assert isinstance(row["input_hash"], str)
    assert len(row["input_hash"]) == 64
    assert isinstance(row["correlation_id"], str)
    assert row["correlation_id"]
    assert isinstance(row["duration_ms"], int)


async def test_sprint_report_dispatch_returns_populated_output(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
    mock_mongo_db: Any,
) -> None:
    """FR-405: the report tool produces every field of SprintReportOutput."""
    issues_payload = {
        "issues": [
            {
                "id": "10042",
                "key": "PROJ-123",
                "fields": {
                    "summary": "Persist sprint metadata",
                    "status": {
                        "id": "10002",
                        "name": "Done",
                        "statusCategory": {"id": 3, "key": "done", "name": "Done"},
                    },
                },
            },
            {
                "id": "10058",
                "key": "PROJ-124",
                "fields": {
                    "summary": "Add JQL search tool",
                    "status": {
                        "id": "10001",
                        "name": "In Progress",
                        "statusCategory": {
                            "id": 4,
                            "key": "indeterminate",
                            "name": "In Progress",
                        },
                    },
                },
            },
        ]
    }
    mock_jira_http.get(f"{BASE_URL}/rest/agile/1.0/sprint/42/issue").mock(
        return_value=httpx.Response(200, json=issues_payload)
    )
    sprint_client = SprintClient(jira_client)
    audit = AuditRepository(mock_mongo_db)
    dispatch = build_sprint_dispatch(sprint_client, audit)

    result = await dispatch["sprint_report"]({"sprint_id": 42})

    assert result["sprint"]["id"] == 42
    assert result["committed"] == 2
    assert result["delivered"] == 1
    assert result["at_risk"] >= 0
    assert {i["key"] for i in result["issues"]} == {"PROJ-123", "PROJ-124"}

    # Read tool must not have written an audit row.
    docs = [d async for d in mock_mongo_db["audit_log"].find({})]
    assert docs == []
