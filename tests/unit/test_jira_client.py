"""Status-code-to-exception mapping tests for the Jira HTTP client.

These tests use respx to intercept httpx requests so they exercise the
full code path inside `JiraClient.request` without any network I/O. Each
test pins a single Jira status code and asserts the precise exception
type or return value that the contract requires.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from jira_mcp.auth.provider import AuthProvider
from jira_mcp.clients.jira import JiraClient
from jira_mcp.utils.errors import (
    AuthenticationError,
    JiraApiError,
    NotFoundError,
    RateLimitError,
    UpstreamError,
)

BASE_URL = "https://example.atlassian.net"
PATH = "/rest/api/3/issue/PROJ-1"
URL = f"{BASE_URL}{PATH}"


class _StaticAuth:
    """Minimal AuthProvider used only by these tests."""

    async def headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    async def refresh(self) -> None:
        return None


def _client(http: httpx.AsyncClient) -> JiraClient:
    """Build a JiraClient with the no-op auth and zero retries."""
    auth: AuthProvider = _StaticAuth()
    return JiraClient(base_url=BASE_URL, auth=auth, http=http, max_retries=0)


@respx.mock
async def test_200_returns_parsed_json() -> None:
    """200 OK is parsed and returned as a dict (FR-104).

    Verifies that a successful Jira response is decoded from JSON and
    surfaced unchanged to the caller.
    """
    payload: dict[str, Any] = {"key": "PROJ-1", "id": "10001"}
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))
    async with httpx.AsyncClient() as http:
        result = await _client(http).request("GET", PATH)
    assert result == payload


@respx.mock
async def test_204_returns_empty_dict() -> None:
    """204 No Content yields an empty dict (FR-104).

    Verifies that the client does not try to JSON-decode an empty body
    and instead returns a stable empty mapping.
    """
    respx.get(URL).mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as http:
        result = await _client(http).request("GET", PATH)
    assert result == {}


@respx.mock
async def test_401_raises_authentication_error() -> None:
    """401 maps to AuthenticationError (FR-104, NFR-201).

    Verifies that credential failures are surfaced as a typed error so
    the dispatcher can render an actionable message instead of a stack
    trace.
    """
    respx.get(URL).mock(
        return_value=httpx.Response(401, json={"errorMessages": ["unauthorized"], "errors": {}})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(AuthenticationError):
            await _client(http).request("GET", PATH)


@respx.mock
async def test_404_raises_not_found_error() -> None:
    """404 maps to NotFoundError (FR-104).

    Verifies that missing resources raise NotFoundError so callers can
    distinguish absence from other failure modes.
    """
    respx.get(URL).mock(
        return_value=httpx.Response(404, json={"errorMessages": ["missing"], "errors": {}})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(NotFoundError) as exc:
            await _client(http).request("GET", PATH)
    assert exc.value.status == 404


@respx.mock
async def test_429_raises_rate_limit_error() -> None:
    """429 maps to RateLimitError (FR-104, NFR-201).

    Verifies that throttle responses raise RateLimitError so the retry
    layer can apply backoff without inspecting the status code itself.
    """
    respx.get(URL).mock(
        return_value=httpx.Response(429, json={"errorMessages": ["slow down"], "errors": {}})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(RateLimitError) as exc:
            await _client(http).request("GET", PATH)
    assert exc.value.status == 429


@respx.mock
async def test_500_raises_upstream_error() -> None:
    """500 maps to UpstreamError (FR-104, NFR-201).

    Verifies that any 5xx is treated as an upstream Jira failure and
    raised as a single error class, regardless of the exact code.
    """
    respx.get(URL).mock(
        return_value=httpx.Response(500, json={"errorMessages": ["boom"], "errors": {}})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(UpstreamError) as exc:
            await _client(http).request("GET", PATH)
    assert exc.value.status == 500


@respx.mock
async def test_400_raises_jira_api_error() -> None:
    """400 maps to the generic JiraApiError (FR-104).

    Verifies that other 4xx responses, which do not have a dedicated
    subclass, fall through to JiraApiError with the original status
    code preserved.
    """
    respx.get(URL).mock(
        return_value=httpx.Response(400, json={"errorMessages": ["bad request"], "errors": {}})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(JiraApiError) as exc:
            await _client(http).request("GET", PATH)
    assert exc.value.status == 400
    assert not isinstance(exc.value, AuthenticationError | NotFoundError | RateLimitError)
