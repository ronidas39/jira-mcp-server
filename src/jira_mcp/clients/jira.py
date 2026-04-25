"""Async HTTP client for the Jira Cloud REST API.

Generic on purpose: this module knows about HTTP, auth, and Jira's status-code
conventions, but not about issues, sprints, or projects. Domain-specific
helpers live in sibling modules (`issues.py`, `sprints.py`, ...) and consume a
`JiraClient` instance.

Transient errors (429 and 5xx) are handled by the ``retry_jira_request``
decorator on ``request``; the per-status mapping below converts non-2xx
responses into typed exceptions before the retry layer decides what to do.
"""

from __future__ import annotations

from http import HTTPStatus
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
from ..utils.retry import retry_jira_request


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

    @retry_jira_request
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

        The ``retry_jira_request`` decorator transparently retries 429 and
        5xx responses with exponential backoff; the public signature is
        unchanged so callers do not need to know about the retry layer.
        """
        headers = await self._auth.headers()
        url = f"{self._base_url}{path}"
        resp = await self._http.request(
            method, url, json=json, params=params, headers=headers
        )
        status = resp.status_code
        if status == HTTPStatus.UNAUTHORIZED:
            raise AuthenticationError("Jira rejected credentials (401).")
        if status == HTTPStatus.NOT_FOUND:
            raise NotFoundError(status, resp.text, "Resource not found.")
        if status == HTTPStatus.TOO_MANY_REQUESTS:
            raise RateLimitError(status, resp.text, "Rate limited by Jira.")
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise UpstreamError(status, resp.text, "Jira upstream error.")
        if status >= HTTPStatus.BAD_REQUEST:
            raise JiraApiError(status, resp.text)
        if status == HTTPStatus.NO_CONTENT or not resp.content:
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
