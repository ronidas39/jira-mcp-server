"""Unit tests for :class:`IssueClient`.

These exercise the issue-domain wrapper against the respx-mocked Jira HTTP
fixtures wired in ``conftest.py``. The goal is to pin the contract for
each method: shape sent on the wire, model returned, and the right typed
error on failure.
"""

from __future__ import annotations

import json as _json

import httpx
import pytest
import respx

from jira_mcp.clients.issues import IssueClient, markdown_to_adf
from jira_mcp.clients.jira import JiraClient
from jira_mcp.models.jira_entities import Issue
from jira_mcp.models.tool_io import CreateIssueInput
from jira_mcp.utils.errors import NotFoundError


async def test_search_returns_summary_page(jira_client: JiraClient) -> None:
    """search() projects the search response into IssueSummary entries."""
    client = IssueClient(jira_client)
    out = await client.search(jql="project = PROJ", max_results=50)
    assert out.total == 3
    assert len(out.issues) == 3
    keys = [i.key for i in out.issues]
    assert keys == ["PROJ-123", "PROJ-124", "PROJ-125"]
    # The summary projection picks up the nested status name correctly.
    first = out.issues[0]
    assert first.status is not None
    assert first.status.name == "In Progress"


async def test_get_uses_issue_from_api_for_flattening(jira_client: JiraClient) -> None:
    """get() returns a fully flattened Issue via Issue.from_api."""
    client = IssueClient(jira_client)
    issue = await client.get("PROJ-123")
    assert isinstance(issue, Issue)
    assert issue.key == "PROJ-123"
    assert issue.summary == "Persist sprint metadata to MongoDB on every poll"
    assert issue.status is not None
    assert issue.status.name == "In Progress"
    assert issue.assignee is not None
    assert issue.assignee.account_id == "557058:abc-1111"
    # Comments come from the nested comment.comments envelope.
    assert len(issue.comments) == 2
    # The raw fields dict is preserved so custom fields stay reachable.
    assert "labels" in issue.fields


async def test_get_404_raises_not_found(
    mock_jira_http: respx.MockRouter, jira_client: JiraClient
) -> None:
    """A 404 from Jira surfaces as NotFoundError, not a generic JiraApiError."""
    mock_jira_http.get(
        "https://example.atlassian.net/rest/api/3/issue/MISSING-1"
    ).mock(return_value=httpx.Response(404, json={"errorMessages": ["gone"]}))
    client = IssueClient(jira_client)
    with pytest.raises(NotFoundError):
        await client.get("MISSING-1")


async def test_create_sends_adf_description_and_returns_key(
    mock_jira_http: respx.MockRouter, jira_client: JiraClient
) -> None:
    """create() wraps the description in ADF and parses the response key."""
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = _json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "id": "10500",
                "key": "PROJ-500",
                "self": "https://example.atlassian.net/rest/api/3/issue/10500",
            },
        )

    mock_jira_http.post(
        "https://example.atlassian.net/rest/api/3/issue"
    ).mock(side_effect=_capture)

    client = IssueClient(jira_client)
    out = await client.create(
        CreateIssueInput(
            project_key="PROJ",
            summary="New task",
            issue_type="Task",
            description="Some context.",
        )
    )
    assert out.key == "PROJ-500"
    assert out.id == "10500"

    body = captured["body"]
    assert isinstance(body, dict)
    fields = body["fields"]
    assert fields["project"] == {"key": "PROJ"}
    assert fields["summary"] == "New task"
    assert fields["issuetype"] == {"name": "Task"}
    # Description must be ADF-shaped, not a raw string.
    desc = fields["description"]
    assert desc == markdown_to_adf("Some context.")


async def test_transition_with_comment_sends_adf_in_update_block(
    mock_jira_http: respx.MockRouter, jira_client: JiraClient
) -> None:
    """transition() places ADF-wrapped comments under update.comment.add."""
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = _json.loads(request.content)
        return httpx.Response(204)

    mock_jira_http.post(
        "https://example.atlassian.net/rest/api/3/issue/PROJ-123/transitions"
    ).mock(side_effect=_capture)

    client = IssueClient(jira_client)
    await client.transition("PROJ-123", "31", comment="Marking as done.")

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["transition"] == {"id": "31"}
    update_block = body["update"]
    assert isinstance(update_block, dict)
    add_entries = update_block["comment"]
    assert isinstance(add_entries, list)
    assert add_entries[0]["add"]["body"] == markdown_to_adf("Marking as done.")


async def test_list_transitions_returns_typed_models(
    jira_client: JiraClient,
) -> None:
    """list_transitions() parses the response into Transition models."""
    client = IssueClient(jira_client)
    out = await client.list_transitions("PROJ-123")
    assert len(out.transitions) == 3
    names = [t.name for t in out.transitions]
    assert names == ["To Do", "In Progress", "Done"]
    # The destination status nests through StatusCategory cleanly.
    done = out.transitions[-1]
    assert done.to is not None
    assert done.to.status_category is not None
    assert done.to.status_category.key == "done"


def test_markdown_to_adf_minimal_shape() -> None:
    """markdown_to_adf() returns a single-paragraph ADF doc unchanged."""
    out = markdown_to_adf("hello world")
    assert out == {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "hello world"}],
            }
        ],
    }
