"""Auth provider Protocol.

The server needs exactly two things from an auth provider: the headers to
attach to an outbound request, and a way to refresh credentials when they
expire. Static API tokens make `refresh()` a no-op; OAuth flows use it to
swap a refresh token for a new access token.
"""

from __future__ import annotations

from typing import Protocol


class AuthProvider(Protocol):
    """Strategy for producing auth headers for outbound Jira requests."""

    async def headers(self) -> dict[str, str]:
        """Return the headers to attach to a Jira HTTP request."""
        ...

    async def refresh(self) -> None:
        """Refresh credentials if needed. No-op for static tokens."""
        ...
