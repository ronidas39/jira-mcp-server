"""Exception hierarchy for the Jira MCP server.

Tools translate these into structured MCP error responses. The dispatcher's
outer handler catches anything else and returns a generic `InternalError`
with a correlation id; the model never sees a Python stack trace.
"""

from __future__ import annotations

from typing import Any


class JiraMcpError(Exception):
    """Base for every error raised by this server."""


class ConfigurationError(JiraMcpError):
    """Misconfiguration detected at startup or runtime."""


class AuthenticationError(JiraMcpError):
    """Auth credentials are missing, invalid, or expired."""


class JiraApiError(JiraMcpError):
    """Jira returned a non-2xx response."""

    def __init__(self, status: int, body: dict[str, Any] | str, message: str = "") -> None:
        super().__init__(message or f"Jira API error {status}")
        self.status = status
        self.body = body


class RateLimitError(JiraApiError):
    """Jira returned 429."""


class UpstreamError(JiraApiError):
    """Jira returned 5xx after retries."""


class NotFoundError(JiraApiError):
    """Jira returned 404."""


class ValidationError(JiraMcpError):
    """Tool input or output failed validation."""


class PersistenceError(JiraMcpError):
    """A MongoDB error that was not handled gracefully upstream."""
