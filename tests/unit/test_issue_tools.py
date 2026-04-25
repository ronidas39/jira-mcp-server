"""Unit tests for the issue MCP tool dispatcher.

These cover the audit-recording contract for write tools and the
opt-in gate on the destructive ``delete_issue`` tool. The dispatcher is
exercised directly without booting the SDK server, since the registration
path is a thin pair of decorator calls and the interesting behavior lives
in ``_dispatch``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from jira_mcp.clients.issues import IssueClient
from jira_mcp.clients.jira import JiraClient
from jira_mcp.db.repositories.audit import AuditRepository
from jira_mcp.tools.issues import IssueToolContext, _dispatch


class _SettingsStub:
    """Minimal stand-in for the real Settings object.

    The dispatcher only reads ``allow_delete_issues``; constructing the
    full pydantic-settings object would require populating every required
    Jira variable, which is unrelated to what these tests check.
    """

    def __init__(self, *, allow_delete_issues: bool) -> None:
        self.allow_delete_issues = allow_delete_issues


@pytest.fixture
def audit_repo(mock_mongo_db: Any) -> AuditRepository:
    """Bind an AuditRepository to the in-memory mongomock database."""
    return AuditRepository(mock_mongo_db)


@pytest.fixture
def issue_ctx_allow_delete(
    jira_client: JiraClient, audit_repo: AuditRepository
) -> IssueToolContext:
    """Tool context with delete enabled."""
    return IssueToolContext(
        issues=IssueClient(jira_client),
        audit=audit_repo,
        settings=_SettingsStub(allow_delete_issues=True),  # type: ignore[arg-type]
    )


@pytest.fixture
def issue_ctx_block_delete(
    jira_client: JiraClient, audit_repo: AuditRepository
) -> IssueToolContext:
    """Tool context with delete disabled (the production default)."""
    return IssueToolContext(
        issues=IssueClient(jira_client),
        audit=audit_repo,
        settings=_SettingsStub(allow_delete_issues=False),  # type: ignore[arg-type]
    )


async def test_create_issue_records_audit_row(
    mock_jira_http: respx.MockRouter,
    mock_mongo_db: Any,
    issue_ctx_allow_delete: IssueToolContext,
) -> None:
    """create_issue writes one audit row with the documented shape."""
    mock_jira_http.post(
        "https://example.atlassian.net/rest/api/3/issue"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "10500",
                "key": "PROJ-500",
                "self": "https://example.atlassian.net/rest/api/3/issue/10500",
            },
        )
    )

    args: dict[str, Any] = {
        "project_key": "PROJ",
        "summary": "Audit me",
        "issue_type": "Task",
        "description": "x" * 600,  # large body should be trimmed in summary
    }
    out = await _dispatch(issue_ctx_allow_delete, "create_issue", args)
    assert out["key"] == "PROJ-500"

    rows = [d async for d in mock_mongo_db["audit_log"].find({})]
    assert len(rows) == 1
    row = rows[0]
    expected = {
        "ts",
        "tool",
        "input_hash",
        "input_summary",
        "response_status",
        "jira_id",
        "actor",
        "duration_ms",
        "correlation_id",
    }
    row.pop("_id", None)
    assert set(row.keys()) == expected
    assert row["tool"] == "create_issue"
    assert row["response_status"] == "ok"
    assert row["jira_id"] == "PROJ-500"
    # Long description bodies are replaced with a length marker so audit
    # rows stay compact.
    summary = row["input_summary"]
    assert isinstance(summary["description"], str)
    assert summary["description"].startswith("<trimmed:")
    # Hash is a sha-256 hex string of length 64.
    assert isinstance(row["input_hash"], str)
    assert len(row["input_hash"]) == 64


async def test_delete_issue_blocked_by_default(
    issue_ctx_block_delete: IssueToolContext,
) -> None:
    """delete_issue raises PermissionError when the operator has not opted in."""
    with pytest.raises(PermissionError, match="allow_delete_issues"):
        await _dispatch(issue_ctx_block_delete, "delete_issue", {"key": "PROJ-1"})


async def test_delete_issue_runs_when_enabled(
    mock_jira_http: respx.MockRouter,
    mock_mongo_db: Any,
    issue_ctx_allow_delete: IssueToolContext,
) -> None:
    """delete_issue posts the DELETE call and writes an audit row when enabled."""
    mock_jira_http.delete(
        "https://example.atlassian.net/rest/api/3/issue/PROJ-9"
    ).mock(return_value=httpx.Response(204))

    out = await _dispatch(issue_ctx_allow_delete, "delete_issue", {"key": "PROJ-9"})
    assert out["key"] == "PROJ-9"
    assert out["updated"] is True
    rows = [d async for d in mock_mongo_db["audit_log"].find({})]
    assert len(rows) == 1
    assert rows[0]["tool"] == "delete_issue"
    assert rows[0]["jira_id"] == "PROJ-9"
