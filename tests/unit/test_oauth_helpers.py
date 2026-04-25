"""Module-level OAuth helper tests.

Covers ``build_authorize_url`` shape, the token exchange call, the
accessible-resources lookup (single tenant pass, multi-tenant fail), and
the refresh call.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from jira_mcp.auth.oauth import (
    ACCESSIBLE_RESOURCES_URL,
    AUTHORIZE_URL,
    TOKEN_URL,
    build_authorize_url,
    exchange_code_for_token,
    fetch_cloud_id,
    refresh_access_token,
)
from jira_mcp.utils.errors import AuthenticationError


def test_build_authorize_url_carries_required_query_params() -> None:
    """The URL is rooted at AUTHORIZE_URL and contains every documented param."""
    url = build_authorize_url(
        client_id="cid",
        redirect_uri="http://localhost:9000/callback",
        scopes="read:jira-work offline_access",
        state="abc123",
    )
    split = urlsplit(url)
    assert f"{split.scheme}://{split.netloc}{split.path}" == AUTHORIZE_URL
    params = parse_qs(split.query)
    assert params["audience"] == ["api.atlassian.com"]
    assert params["client_id"] == ["cid"]
    assert params["scope"] == ["read:jira-work offline_access"]
    assert params["redirect_uri"] == ["http://localhost:9000/callback"]
    assert params["state"] == ["abc123"]
    assert params["response_type"] == ["code"]
    assert params["prompt"] == ["consent"]


@respx.mock
async def test_exchange_code_for_token_returns_body() -> None:
    """A 200 response is parsed and returned to the caller verbatim."""
    payload = {
        "access_token": "at-1",
        "refresh_token": "rt-1",
        "expires_in": 3600,
        "scope": "read:jira-work offline_access",
    }
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=payload))
    async with httpx.AsyncClient() as http:
        body = await exchange_code_for_token(
            http, "cid", "secret", "code-1", "http://localhost:9000/callback"
        )
    assert body == payload
    assert route.called


@respx.mock
async def test_exchange_code_for_token_raises_on_non_2xx() -> None:
    """A 400 from the token endpoint surfaces as AuthenticationError."""
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    async with httpx.AsyncClient() as http:
        with pytest.raises(AuthenticationError):
            await exchange_code_for_token(
                http, "cid", "secret", "bad", "http://localhost:9000/callback"
            )


@respx.mock
async def test_fetch_cloud_id_returns_single_id() -> None:
    """A single accessible-resources entry yields its id."""
    respx.get(ACCESSIBLE_RESOURCES_URL).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "cloud-1", "name": "ACME"}],
        )
    )
    async with httpx.AsyncClient() as http:
        cloud_id = await fetch_cloud_id(http, "at-1")
    assert cloud_id == "cloud-1"


@respx.mock
async def test_fetch_cloud_id_raises_on_zero_results() -> None:
    """An empty list raises ValueError so the operator knows to grant the app."""
    respx.get(ACCESSIBLE_RESOURCES_URL).mock(return_value=httpx.Response(200, json=[]))
    async with httpx.AsyncClient() as http:
        with pytest.raises(ValueError, match="no Jira sites"):
            await fetch_cloud_id(http, "at-1")


@respx.mock
async def test_fetch_cloud_id_raises_on_multiple_results() -> None:
    """Two or more entries raise ValueError to avoid picking the wrong tenant."""
    respx.get(ACCESSIBLE_RESOURCES_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "cloud-1", "name": "ACME"},
                {"id": "cloud-2", "name": "Other"},
            ],
        )
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(ValueError, match="multiple sites"):
            await fetch_cloud_id(http, "at-1")


@respx.mock
async def test_refresh_access_token_returns_body() -> None:
    """A successful refresh response is returned as a dict."""
    payload = {
        "access_token": "at-2",
        "refresh_token": "rt-2",
        "expires_in": 3600,
        "scope": "read:jira-work offline_access",
    }
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=payload))
    async with httpx.AsyncClient() as http:
        body = await refresh_access_token(http, "cid", "secret", "rt-1")
    assert body == payload


@respx.mock
async def test_refresh_access_token_raises_on_invalid_grant() -> None:
    """A 400 invalid_grant surfaces as AuthenticationError so callers can re-login."""
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    async with httpx.AsyncClient() as http:
        with pytest.raises(AuthenticationError):
            await refresh_access_token(http, "cid", "secret", "rt-stale")
