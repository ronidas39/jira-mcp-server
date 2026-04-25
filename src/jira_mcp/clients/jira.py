"""Async HTTP client for the Jira Cloud REST API.

Generic on purpose: this module knows about HTTP, auth, and Jira's status-code
conventions, but not about issues, sprints, or projects. Domain-specific
helpers live in sibling modules (`issues.py`, `sprints.py`, ...) and consume a
`JiraClient` instance.

The retry layer for 429 and 5xx responses is intentionally not in here yet; it
lands in M1 alongside the higher-level helpers, so the test surface stays
small while we shake out the auth flow.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..auth.provider import AuthProvider
from ..utils.errors import (
    AuthenticationError,
    JiraApiError,
    NotFoundError,
    RateLimitError,
    UpstreamError,
)


class JiraClient:
    """Thin async wrapper around the Jira Cloud REST API v3."""

    def __init__(
        self,
        base_url: str,
        auth: AuthProvider,
        http: httpx.AsyncClient,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._http = http
        self._max_retries = max_retries

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a Jira API request and translate status codes to typed errors.

        Each Jira status code maps to a specific error class so callers can
        decide their own policy (retry, surface to the user, swallow). The
        response body is included in the error so the model gets enough
        context to explain the failure without having to re-issue the call.
        """
        headers = await self._auth.headers()
        url = f"{self._base_url}{path}"
        resp = await self._http.request(
            method, url, json=json, params=params, headers=headers
        )
        if resp.status_code == 401:
            raise AuthenticationError("Jira rejected credentials (401).")
        if resp.status_code == 404:
            raise NotFoundError(404, resp.text, "Resource not found.")
        if resp.status_code == 429:
            raise RateLimitError(429, resp.text, "Rate limited by Jira.")
        if resp.status_code >= 500:
            raise UpstreamError(resp.status_code, resp.text, "Jira upstream error.")
        if resp.status_code >= 400:
            raise JiraApiError(resp.status_code, resp.text)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()  # type: ignore[no-any-return]

    async def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return await self.request("DELETE", path, **kwargs)
