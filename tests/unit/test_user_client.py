"""Unit tests for :class:`UserClient`.

Covers list_users (with and without project scoping), the email and display
name disambiguation paths in resolve(), and the get_self() probe.
"""

from __future__ import annotations

import httpx
import respx

from jira_mcp.clients.jira import JiraClient
from jira_mcp.clients.users import UserClient

JIRA_BASE_URL = "https://example.atlassian.net"


async def test_list_users_returns_seeded_directory(
    jira_client: JiraClient,
) -> None:
    """The default route returns the two-user fixture directory."""
    client = UserClient(jira_client)
    users = await client.list_users()
    assert len(users) == 2
    emails = {u.email_address for u in users}
    assert emails == {"alice@example.com", "bob@example.com"}


async def test_list_users_with_project_uses_assignable_endpoint(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """A non-null project_key switches to /user/assignable/search."""
    payload = [
        {
            "accountId": "557058:abc-1111",
            "displayName": "Alice Engineer",
            "emailAddress": "alice@example.com",
            "active": True,
        }
    ]
    route = mock_jira_http.get(
        f"{JIRA_BASE_URL}/rest/api/3/user/assignable/search",
    ).mock(return_value=httpx.Response(200, json=payload))

    client = UserClient(jira_client)
    users = await client.list_users(query="alice", project_key="PROJ")
    assert len(users) == 1
    assert users[0].account_id == "557058:abc-1111"
    assert route.called
    request = route.calls.last.request
    assert "project=PROJ" in str(request.url)
    assert "query=alice" in str(request.url)


async def test_resolve_returns_unique_email_match(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """resolve() picks the row whose emailAddress matches the input exactly."""
    payload = [
        {
            "accountId": "557058:abc-1111",
            "displayName": "Alice Engineer",
            "emailAddress": "alice@example.com",
            "active": True,
        },
        {
            "accountId": "557058:zzz-9999",
            "displayName": "Alice Other",
            "emailAddress": "alice.other@example.com",
            "active": True,
        },
    ]
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/user/search").mock(
        return_value=httpx.Response(200, json=payload)
    )

    client = UserClient(jira_client)
    user = await client.resolve("alice@example.com")
    assert user is not None
    assert user.account_id == "557058:abc-1111"


async def test_resolve_returns_none_for_ambiguous_displayname(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """Two users share displayName but have different emails; resolver bails.

    This exercises the disambiguation policy: when a label cannot be tied
    to exactly one user, returning ``None`` is safer than picking the first
    hit, because Jira does not guarantee any meaningful ordering.
    """
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
    user = await client.resolve("Alex Smith")
    assert user is None


async def test_resolve_returns_none_for_no_matches(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """Empty search results produce a None resolution."""
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/user/search").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = UserClient(jira_client)
    user = await client.resolve("nobody@example.com")
    assert user is None


async def test_resolve_displayname_picks_unique_match(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """Only one row's displayName matches; resolver returns that user."""
    payload = [
        {
            "accountId": "557058:def-2222",
            "displayName": "Bob Manager",
            "emailAddress": "bob@example.com",
            "active": True,
        },
        {
            "accountId": "557058:other",
            "displayName": "Bobby Robot",
            "emailAddress": "bobby@example.com",
            "active": True,
        },
    ]
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/user/search").mock(
        return_value=httpx.Response(200, json=payload)
    )

    client = UserClient(jira_client)
    user = await client.resolve("Bob Manager")
    assert user is not None
    assert user.account_id == "557058:def-2222"


async def test_get_self_returns_caller(
    jira_client: JiraClient,
    mock_jira_http: respx.MockRouter,
) -> None:
    """/myself is parsed into a User."""
    mock_jira_http.get(f"{JIRA_BASE_URL}/rest/api/3/myself").mock(
        return_value=httpx.Response(
            200,
            json={
                "accountId": "557058:self-9999",
                "displayName": "Bot Account",
                "emailAddress": "bot@example.com",
                "active": True,
            },
        )
    )
    client = UserClient(jira_client)
    me = await client.get_self()
    assert me.account_id == "557058:self-9999"
    assert me.email_address == "bot@example.com"
