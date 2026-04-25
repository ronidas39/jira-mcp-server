"""API-token auth (HTTP Basic).

Atlassian's documented scheme is `Basic base64(email:token)`, even though the
"token" is not really a password. We keep the secret in a `SecretStr` so it
will not show up in repr output or structlog records that happen to grab the
provider.
"""

from __future__ import annotations

import base64

from pydantic import SecretStr

from .provider import AuthProvider


class ApiTokenAuth:
    """Basic auth using an Atlassian email plus an API token."""

    def __init__(self, email: str, api_token: SecretStr) -> None:
        self._email = email
        self._token = api_token

    async def headers(self) -> dict[str, str]:
        creds = f"{self._email}:{self._token.get_secret_value()}".encode()
        encoded = base64.b64encode(creds).decode("ascii")
        return {
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
        }

    async def refresh(self) -> None:
        """Static token: nothing to refresh."""


# Compile-time check that ApiTokenAuth satisfies the AuthProvider Protocol.
# The annotation alone is enough; mypy will catch any drift.
_PROVIDER_CHECK: type[AuthProvider] = ApiTokenAuth  # type: ignore[type-abstract]
