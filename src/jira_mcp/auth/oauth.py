"""Atlassian Jira Cloud OAuth 2.0 (3LO) provider.

Implements the ``AuthProvider`` Protocol for the three-legged OAuth flow.
Atlassian's flow has two endpoints we care about: the authorize URL on
``auth.atlassian.com`` (used once, by ``scripts/oauth_login.py``) and the
token URL on the same host, which we hit during a refresh. After the first
exchange we also call ``/oauth/token/accessible-resources`` to find the
``cloud_id`` for the tenant; subsequent Jira REST calls go through the
``api.atlassian.com/ex/jira/{cloudId}`` proxy rather than the customer's
own ``*.atlassian.net`` host.

The provider keeps the access token in memory after a first load to avoid a
Mongo round-trip on every Jira request. The in-memory copy is invalidated
whenever ``refresh()`` runs so a stale token cannot survive a refresh.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from ..db.repositories.oauth_tokens import TokenRecord, TokenRepository
from ..utils.errors import AuthenticationError
from .provider import AuthProvider

# Atlassian OAuth endpoints; pinned because they are stable parts of the
# Atlassian developer contract and we never want to point at staging by
# accident.
AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"  # noqa: S105  (URL, not a secret)
ACCESSIBLE_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

# HTTP error threshold; pulled out so ruff's PLR2004 (magic value) does not
# light up on every status check.
_HTTP_ERROR_FLOOR = 400

# The audience is constant for Atlassian Cloud; bake it into the helper so
# callers cannot accidentally pass the wrong value.
_AUDIENCE = "api.atlassian.com"

# Refresh ahead of expiry by this many seconds so a request that arrives
# right at the boundary still travels with a fresh token. One minute is the
# common Atlassian recommendation and matches our test expectations.
_REFRESH_LEEWAY_SECONDS = 60


def build_authorize_url(
    client_id: str,
    redirect_uri: str,
    scopes: str,
    state: str,
) -> str:
    """Return the Atlassian authorize URL for a 3LO consent screen.

    Args:
        client_id: The OAuth app's client id from developer.atlassian.com.
        redirect_uri: The exact redirect URI registered with the OAuth app.
        scopes: A space-separated scope string. ``offline_access`` must be
            present, otherwise Atlassian will not return a refresh token.
        state: A random string the caller will validate when the user is
            redirected back. Required for CSRF protection.

    Returns:
        A fully formed authorize URL ready to open in a browser. ``prompt``
        is set to ``consent`` so the user is always asked, which avoids the
        common mistake of an outdated cached grant during dev iteration.
    """
    params = {
        "audience": _AUDIENCE,
        "client_id": client_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_token(
    http: httpx.AsyncClient,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange a one-time authorization code for an access plus refresh token.

    Args:
        http: A shared async HTTP client.
        client_id: The OAuth app's client id.
        client_secret: The OAuth app's client secret.
        code: The ``code`` query parameter from the redirect URL.
        redirect_uri: The redirect URI registered with the OAuth app; must
            match the value used when building the authorize URL.

    Returns:
        The parsed token response body. Atlassian returns at minimum
        ``access_token``, ``refresh_token``, ``expires_in``, and ``scope``.

    Raises:
        AuthenticationError: When the token endpoint returns a non-2xx
            response. The Atlassian error body is included in the message
            so the operator can see the underlying ``error`` code.
    """
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    resp = await http.post(TOKEN_URL, json=payload)
    if resp.status_code >= _HTTP_ERROR_FLOOR:
        msg = f"OAuth code exchange failed ({resp.status_code}): {resp.text}"
        raise AuthenticationError(msg)
    body = resp.json()
    if not isinstance(body, dict):
        msg = "OAuth token endpoint returned a non-object body"
        raise AuthenticationError(msg)
    return body


async def fetch_cloud_id(http: httpx.AsyncClient, access_token: str) -> str:
    """Resolve the ``cloud_id`` for the tenant the access token belongs to.

    Atlassian apps can be installed on multiple Cloud tenants, but this
    server is wired for a single tenant per deployment. We fail loudly if
    the response carries zero or more than one resource: silently picking
    the first item would route requests to a tenant the operator did not
    intend.

    Args:
        http: A shared async HTTP client.
        access_token: A valid Atlassian access token.

    Returns:
        The ``id`` of the single accessible Jira resource.

    Raises:
        AuthenticationError: When the accessible-resources endpoint returns
            a non-2xx response.
        ValueError: When zero or more than one resource is returned.
    """
    resp = await http.get(
        ACCESSIBLE_RESOURCES_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    if resp.status_code >= _HTTP_ERROR_FLOOR:
        msg = f"accessible-resources failed ({resp.status_code}): {resp.text}"
        raise AuthenticationError(msg)
    body = resp.json()
    if not isinstance(body, list) or not body:
        msg = "accessible-resources returned no Jira sites for this token"
        raise ValueError(msg)
    if len(body) > 1:
        ids = ", ".join(str(item.get("id")) for item in body)
        msg = (
            "accessible-resources returned multiple sites; pick one by "
            f"setting JIRA_OAUTH_CLOUD_ID explicitly. Candidates: {ids}"
        )
        raise ValueError(msg)
    cloud_id = body[0].get("id")
    if not isinstance(cloud_id, str) or not cloud_id:
        msg = "accessible-resources response is missing a string id"
        raise ValueError(msg)
    return cloud_id


async def refresh_access_token(
    http: httpx.AsyncClient,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> dict[str, Any]:
    """Swap a refresh token for a new access plus refresh token pair.

    Atlassian rotates the refresh token on every call, so callers must
    persist the entire response, not just ``access_token``. Forgetting to
    save the new refresh token is the most common cause of "my OAuth
    integration suddenly stopped working" on this platform.

    Args:
        http: A shared async HTTP client.
        client_id: The OAuth app's client id.
        client_secret: The OAuth app's client secret.
        refresh_token: The refresh token last persisted for the tenant.

    Returns:
        The parsed token response body.

    Raises:
        AuthenticationError: When the token endpoint refuses the refresh
            token (HTTP 4xx). The error body is included so the operator
            can identify a revoked grant and re-run the login script.
    """
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    resp = await http.post(TOKEN_URL, json=payload)
    if resp.status_code >= _HTTP_ERROR_FLOOR:
        msg = f"OAuth refresh failed ({resp.status_code}): {resp.text}"
        raise AuthenticationError(msg)
    body = resp.json()
    if not isinstance(body, dict):
        msg = "OAuth token endpoint returned a non-object body"
        raise AuthenticationError(msg)
    return body


class OAuthProvider:
    """Atlassian OAuth 2.0 (3LO) ``AuthProvider`` with refresh support."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: str,
        token_repo: TokenRepository,
        http: httpx.AsyncClient,
        cloud_id: str,
    ) -> None:
        """Bind credentials and the persistence layer.

        Args:
            client_id: OAuth client id.
            client_secret: OAuth client secret.
            redirect_uri: Redirect URI registered with the OAuth app. Stored
                so a future re-issue of ``refresh_token`` can be performed
                with the same parameters as the initial exchange.
            scopes: Space-separated scope string the app was granted.
            token_repo: Persistence layer for the token record.
            http: A shared async HTTP client used for token endpoint calls.
            cloud_id: The Atlassian Cloud tenant identifier; used as the
                primary key when reading and writing the token record.
        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._scopes = scopes
        self._repo = token_repo
        self._http = http
        self._cloud_id = cloud_id
        # In-memory cache of the most recently loaded record. Prevents a
        # Mongo round-trip on every Jira call; invalidated whenever
        # ``refresh()`` runs so a stale token cannot outlive its refresh.
        self._cached: dict[str, Any] | None = None

    @property
    def cloud_id(self) -> str:
        """The Atlassian Cloud tenant identifier this provider is bound to."""
        return self._cloud_id

    async def headers(self) -> dict[str, str]:
        """Return Bearer auth headers, refreshing the access token if needed.

        Returns:
            A dict with ``Authorization`` and ``Accept`` headers suitable
            for an Atlassian REST call.

        Raises:
            AuthenticationError: When no token record exists for the
                tenant, or when the refresh fails.
        """
        record = await self._load()
        if self._is_near_expiry(record["expires_at"]):
            await self.refresh()
            record = await self._load()
        token = record["access_token"]
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def refresh(self) -> None:
        """Refresh the access token using the persisted refresh token.

        Persists the new pair, invalidates the in-memory cache, and updates
        ``expires_at``. Atlassian rotates the refresh token on every call,
        so the new ``refresh_token`` is what we save, not the old one.

        Raises:
            AuthenticationError: When the token endpoint rejects the
                refresh token. The operator must re-run the login script.
        """
        record = await self._load_from_store()
        body = await refresh_access_token(
            self._http,
            self._client_id,
            self._client_secret,
            record["refresh_token"],
        )
        new_record = self._record_from_token_response(
            body, fallback_refresh=record["refresh_token"]
        )
        await self._repo.upsert(new_record)
        # Invalidate the cache so the next ``headers()`` call reloads from
        # Mongo and observes the freshly persisted token.
        self._cached = None

    async def _load(self) -> dict[str, Any]:
        """Return the cached record, loading from Mongo on a miss."""
        if self._cached is not None:
            return self._cached
        self._cached = await self._load_from_store()
        return self._cached

    async def _load_from_store(self) -> dict[str, Any]:
        """Read the persisted record or raise if no token has been stored."""
        record = await self._repo.get(self._cloud_id)
        if record is None:
            msg = (
                "No OAuth token stored for cloud_id="
                f"{self._cloud_id}; run scripts/oauth_login.py first."
            )
            raise AuthenticationError(msg)
        return record

    def _is_near_expiry(self, expires_at: Any) -> bool:
        """Return True if ``expires_at`` is within the refresh leeway.

        Mongo drivers occasionally return naive datetimes (the BSON date
        round-trip can drop tzinfo). We treat naive values as UTC so the
        comparison stays correct in both cases.
        """
        if not isinstance(expires_at, datetime):
            return True
        normalised: datetime = expires_at
        if normalised.tzinfo is None:
            normalised = normalised.replace(tzinfo=UTC)
        threshold = datetime.now(tz=UTC) + timedelta(seconds=_REFRESH_LEEWAY_SECONDS)
        return normalised <= threshold

    def _record_from_token_response(
        self, body: dict[str, Any], *, fallback_refresh: str
    ) -> TokenRecord:
        """Build a ``TokenRecord`` from an Atlassian token response body.

        Atlassian usually rotates the refresh token on each refresh, but the
        spec allows it to be omitted; we fall back to the previous value in
        that case so we never accidentally drop the only credential we have.
        """
        access_token = body.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            msg = "OAuth response missing access_token"
            raise AuthenticationError(msg)
        refresh_token = body.get("refresh_token") or fallback_refresh
        if not isinstance(refresh_token, str) or not refresh_token:
            msg = "OAuth response missing refresh_token"
            raise AuthenticationError(msg)
        expires_in_raw = body.get("expires_in", 0)
        try:
            expires_in = int(expires_in_raw)
        except (TypeError, ValueError) as exc:
            msg = f"OAuth response has non-integer expires_in: {expires_in_raw!r}"
            raise AuthenticationError(msg) from exc
        scope = body.get("scope")
        scopes = scope if isinstance(scope, str) and scope else self._scopes
        now = datetime.now(tz=UTC)
        return TokenRecord(
            _id=self._cloud_id,
            cloud_id=self._cloud_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=now + timedelta(seconds=expires_in),
            scopes=scopes,
            updated_at=now,
        )


# Compile-time check that OAuthProvider satisfies the AuthProvider Protocol.
# The annotation alone is enough; mypy will catch any drift.
_PROVIDER_CHECK: type[AuthProvider] = OAuthProvider


__all__ = [
    "ACCESSIBLE_RESOURCES_URL",
    "AUTHORIZE_URL",
    "TOKEN_URL",
    "OAuthProvider",
    "build_authorize_url",
    "exchange_code_for_token",
    "fetch_cloud_id",
    "refresh_access_token",
]
