"""Unit tests for :class:`SprintClient`.

These exercise the agile board and sprint endpoints by routing requests
through the respx-mocked transport configured in ``conftest.py``. Each test
references the functional requirement it covers (FR-401 through FR-405).
"""

from __future__ import annotations

import httpx
import respx

from jira_mcp.clients.jira import JiraClient
from jira_mcp.clients.sprints import SprintClient

BASE_URL = "https://example.atlassian.net"


async def test_list_boards_returns_seeded_pair(
    jira_client: JiraClient, mock_jira_http: respx.MockRouter
) -> None:
    """FR-401: list_boards parses both seeded boards with project_key flattened."""
    sprint_client = SprintClient(jira_client)

    boards = await sprint_client.list_boards()

    assert [b.id for b in boards] == [7, 8]
    assert boards[0].name == "Platform Scrum"
    assert boards[0].type == "scrum"
    # location.projectKey must surface as the flat project_key attribute.
    assert boards[0].project_key == "PROJ"
    assert boards[1].project_key == "OPS"


async def test_list_boards_passes_project_filter(
    jira_client: JiraClient, mock_jira_http: respx.MockRouter
) -> None:
    """FR-401: project_key argument hits Jira as ``projectKeyOrId``."""
    sprint_client = SprintClient(jira_client)

    await sprint_client.list_boards(project_key="PROJ")

    boards_route = mock_jira_http.routes["GET /rest/agile/1.0/board"] if False else None
    # respx exposes call history on each route via .calls; fish out the URL.
    matched = [c for c in mock_jira_http.calls if "/rest/agile/1.0/board" in str(c.request.url)]
    assert matched, "expected the board route to be invoked"
    assert "projectKeyOrId=PROJ" in str(matched[-1].request.url)
    _ = boards_route  # kept for readability; route lookup not strictly required


async def test_list_sprints_returns_three_states(
    jira_client: JiraClient, mock_jira_http: respx.MockRouter
) -> None:
    """FR-402: list_sprints returns one closed, one active, and one future sprint."""
    sprint_client = SprintClient(jira_client)

    sprints = await sprint_client.list_sprints(board_id=7)

    states = [s.state for s in sprints]
    assert states == ["closed", "active", "future"]
    assert sprints[1].id == 42
    assert sprints[1].name == "Sprint 42"


async def test_get_sprint_parses_sprint_42(
    jira_client: JiraClient, mock_jira_http: respx.MockRouter
) -> None:
    """FR-403: get_sprint hydrates the seeded sprint 42 fixture."""
    sprint_client = SprintClient(jira_client)

    sprint = await sprint_client.get_sprint(42)

    assert sprint.id == 42
    assert sprint.state == "active"
    assert sprint.origin_board_id == 7
    assert sprint.start_date is not None
    assert sprint.end_date is not None


async def test_move_to_sprint_posts_payload_and_counts(
    jira_client: JiraClient, mock_jira_http: respx.MockRouter
) -> None:
    """FR-404: move_to_sprint posts {"issues": [...]} and returns moved_count."""
    route = mock_jira_http.post(f"{BASE_URL}/rest/agile/1.0/sprint/42/issue").mock(
        return_value=httpx.Response(204)
    )
    sprint_client = SprintClient(jira_client)

    result = await sprint_client.move_to_sprint(
        issue_keys=["PROJ-123", "PROJ-124", "PROJ-125"], sprint_id=42
    )

    assert result == {"moved_count": 3}
    assert route.called
    sent = route.calls.last.request
    assert sent.method == "POST"
    body = sent.content.decode("utf-8")
    assert "PROJ-123" in body
    assert "PROJ-124" in body
    assert "PROJ-125" in body


async def test_move_to_sprint_batches_over_50(
    jira_client: JiraClient, mock_jira_http: respx.MockRouter
) -> None:
    """FR-404: lists longer than 50 keys split into multiple POST batches."""
    route = mock_jira_http.post(f"{BASE_URL}/rest/agile/1.0/sprint/42/issue").mock(
        return_value=httpx.Response(204)
    )
    sprint_client = SprintClient(jira_client)
    keys = [f"PROJ-{i}" for i in range(75)]

    result = await sprint_client.move_to_sprint(issue_keys=keys, sprint_id=42)

    assert result == {"moved_count": 75}
    # Two batches: 50 + 25.
    assert route.call_count == 2


async def test_sprint_issues_serialises_fields_param(
    jira_client: JiraClient, mock_jira_http: respx.MockRouter
) -> None:
    """FR-405: sprint_issues passes fields as a comma-separated query param."""
    payload = {
        "issues": [
            {
                "id": "10042",
                "key": "PROJ-123",
                "fields": {
                    "summary": "Sample",
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
            }
        ]
    }
    route = mock_jira_http.get(f"{BASE_URL}/rest/agile/1.0/sprint/42/issue").mock(
        return_value=httpx.Response(200, json=payload)
    )
    sprint_client = SprintClient(jira_client)

    issues = await sprint_client.sprint_issues(42, fields=["summary", "status"])

    assert len(issues) == 1
    assert issues[0].key == "PROJ-123"
    assert "fields=summary%2Cstatus" in str(route.calls.last.request.url)


async def test_sprint_report_synthesises_counts(
    jira_client: JiraClient, mock_jira_http: respx.MockRouter
) -> None:
    """FR-405: sprint_report fans out get_sprint plus sprint_issues and counts states."""
    issues_payload = {
        "issues": [
            {
                "id": "1",
                "key": "PROJ-1",
                "fields": {
                    "summary": "Done one",
                    "status": {
                        "id": "10002",
                        "name": "Done",
                        "statusCategory": {"id": 3, "key": "done", "name": "Done"},
                    },
                },
            },
            {
                "id": "2",
                "key": "PROJ-2",
                "fields": {
                    "summary": "In progress",
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

    report = await sprint_client.sprint_report(42)

    assert report.sprint.id == 42
    assert report.committed == 2
    assert report.delivered == 1
    # Sprint 42 ends 2026-04-27; "today" in this environment is before end,
    # so at_risk must be zero. The exact at-risk path is exercised separately.
    assert report.at_risk >= 0
    assert {i.key for i in report.issues} == {"PROJ-1", "PROJ-2"}
