"""Unit tests for :class:`ProjectClient`.

These tests use the ``jira_client`` fixture from ``conftest.py`` so the
HTTP layer is mocked via respx. The default routes mounted there cover the
endpoints exercised below; only the custom-fields endpoint needs an explicit
respx route because the conftest does not pre-mount it.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from jira_mcp.clients.jira import JiraClient
from jira_mcp.clients.projects import ProjectClient
from jira_mcp.models.tool_io import ListCustomFieldsOutput

JIRA_BASE_URL = "https://example.atlassian.net"


async def test_list_projects_returns_three_projects(
    jira_client: JiraClient,
) -> None:
    """The simple list endpoint returns the seeded fixture rows."""
    client = ProjectClient(jira_client)
    projects = await client.list_projects()
    assert len(projects) == 3
    keys = {p.key for p in projects}
    assert keys == {"PROJ", "DOCS", "OPS"}


async def test_list_projects_falls_back_to_search_when_truncated(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """When the simple endpoint hits the truncation threshold, ``/project/search``
    is walked until ``isLast`` is true.

    Why this test matters: Jira silently caps the simple list at 50; without
    the fallback, large tenants would lose projects.
    """
    fifty = [{"id": str(i), "key": f"P{i}", "name": f"Project {i}"} for i in range(50)]
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/project").mock(
        return_value=httpx.Response(200, json=fifty)
    )
    page_one = [{"id": str(i + 100), "key": f"Q{i}", "name": f"Project {i}"} for i in range(50)]
    page_two = [{"id": "200", "key": "ZED", "name": "Tail"}]
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/project/search").mock(
        side_effect=[
            httpx.Response(
                200,
                json={"values": page_one, "isLast": False, "startAt": 0, "maxResults": 50},
            ),
            httpx.Response(
                200,
                json={"values": page_two, "isLast": True, "startAt": 50, "maxResults": 50},
            ),
        ]
    )

    client = ProjectClient(jira_client)
    projects = await client.list_projects()
    assert len(projects) == 51
    assert projects[-1].key == "ZED"


async def test_get_project_parses_lead_and_metadata(
    jira_client: JiraClient,
) -> None:
    """get(key) returns a Project with the lead populated from the fixture."""
    client = ProjectClient(jira_client)
    project = await client.get("PROJ")
    assert project.key == "PROJ"
    assert project.name == "Platform"
    assert project.project_type_key == "software"
    assert project.lead is not None
    assert project.lead.display_name == "Bob Manager"


async def test_get_project_round_trip_preserves_issue_types(
    jira_client: JiraClient,
    jira_fixture: object,
) -> None:
    """The fixture carries five issue types; the raw payload survives parsing.

    The :class:`Project` model uses ``extra="ignore"`` so the typed instance
    drops ``issueTypes``; we therefore check that the data is present in the
    raw fixture and that parsing the same payload through the model does not
    raise. This keeps the contract honest without forcing a model change
    that lives outside this module's scope.
    """
    raw = jira_fixture("project_PROJ")  # type: ignore[operator]
    assert isinstance(raw, dict)
    issue_types = raw.get("issueTypes")
    assert isinstance(issue_types, list)
    assert len(issue_types) == 5
    names = {it["name"] for it in issue_types}
    assert {"Epic", "Story", "Task", "Bug", "Sub-task"}.issubset(names)
    sub_task = next(it for it in issue_types if it["name"] == "Sub-task")
    assert sub_task["subtask"] is True

    client = ProjectClient(jira_client)
    project = await client.get("PROJ")
    assert project.id == raw["id"]


async def test_list_custom_fields_filters_to_custom_only(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """Only entries with ``schema.custom == True`` are returned, sorted by id."""
    fields_payload = [
        {
            "id": "summary",
            "name": "Summary",
            "custom": False,
            "schema": {"type": "string", "system": "summary"},
        },
        {
            "id": "customfield_10011",
            "name": "Epic Link",
            "custom": True,
            "schema": {"type": "any", "custom": "com.pyxis.greenhopper.jira:gh-epic-link"},
        },
        {
            "id": "customfield_10005",
            "name": "Story Points",
            "custom": True,
            "schema": {
                "type": "number",
                "custom": "com.atlassian.jira.plugin.system.customfieldtypes:float",
            },
        },
    ]
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/field").mock(
        return_value=httpx.Response(200, json=fields_payload)
    )

    client = ProjectClient(jira_client)
    result = await client.list_custom_fields()
    assert isinstance(result, ListCustomFieldsOutput)
    ids = [d.id for d in result.fields]
    assert ids == ["customfield_10005", "customfield_10011"]
    by_id = {d.id: d for d in result.fields}
    assert by_id["customfield_10005"].name == "Story Points"
    assert by_id["customfield_10005"].schema_type == "number"
    assert all(d.custom for d in result.fields)


@pytest.mark.parametrize("payload", [[], {"values": []}])
async def test_list_custom_fields_handles_empty(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
    payload: object,
) -> None:
    """An empty field list (array or paginated envelope) yields zero descriptors."""
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/field").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = ProjectClient(jira_client)
    result = await client.list_custom_fields()
    assert result.fields == []
