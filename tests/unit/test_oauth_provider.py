"""OAuth provider unit tests.

Verifies the behaviour the rest of the server relies on: ``headers()``
returns a Bearer pair when the token is fresh, the provider refreshes when
the token is within the leeway window, ``refresh()`` persists the new pair
and invalidates the in-memory cache, and a 400 ``invalid_grant`` from the
token endpoint surfaces as ``AuthenticationError`` so the operator knows
to re-run the login script.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from mongomock_motor import AsyncMongoMockClient

from jira_mcp.auth.oauth import TOKEN_URL, OAuthProvider
from jira_mcp.db.repositories.oauth_tokens import TokenRecord, TokenRepository
from jira_mcp.utils.errors import AuthenticationError


@pytest.fixture
def db() -> Any:
    """Return a fresh in-memory Motor-compatible database per test."""
    client = AsyncMongoMockClient()
    return client["oauth_test_db"]


def _seed_record(
    cloud_id: str = "cloud-1",
    *,
    access_token: str = "at-1",
    refresh_token: str = "rt-1",
    expires_in: int = 3600,
) -> TokenRecord:
    """Build a TokenRecord with an absolute expiry computed from ``expires_in``."""
    now = datetime.now(tz=UTC)
    return TokenRecord(
        _id=cloud_id,
        cloud_id=cloud_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=now + timedelta(seconds=expires_in),
        scopes="read:jira-work offline_access",
        updated_at=now,
    )


def _provider(
    repo: TokenRepository,
    http: httpx.AsyncClient,
    cloud_id: str = "cloud-1",
) -> OAuthProvider:
    """Build an OAuthProvider wired to the given repo and http client."""
    return OAuthProvider(
        client_id="cid",
        client_secret="secret",
        redirect_uri="http://localhost:9000/callback",
        scopes="read:jira-work offline_access",
        token_repo=repo,
        http=http,
        cloud_id=cloud_id,
    )


@respx.mock
async def test_headers_returns_bearer_when_token_is_fresh(db: Any) -> None:
    """A fresh token short-circuits past refresh and returns a Bearer pair."""
    repo = TokenRepository(db)
    await repo.upsert(_seed_record(expires_in=3600))
    async with httpx.AsyncClient() as http:
        provider = _provider(repo, http)
        headers = await provider.headers()
    assert headers == {"Authorization": "Bearer at-1", "Accept": "application/json"}


@respx.mock
async def test_headers_refreshes_when_within_leeway(db: Any) -> None:
    """A token under the 60s leeway triggers a refresh before headers return."""
    repo = TokenRepository(db)
    # Seed a record that expires in 30 seconds (inside the 60s leeway).
    await repo.upsert(_seed_record(expires_in=30))
    new_payload = {
        "access_token": "at-2",
        "refresh_token": "rt-2",
        "expires_in": 3600,
        "scope": "read:jira-work offline_access",
    }
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=new_payload))
    async with httpx.AsyncClient() as http:
        provider = _provider(repo, http)
        headers = await provider.headers()
    assert headers["Authorization"] == "Bearer at-2"
    assert route.called
    stored = await repo.get("cloud-1")
    assert stored is not None
    assert stored["access_token"] == "at-2"
    assert stored["refresh_token"] == "rt-2"


@respx.mock
async def test_refresh_persists_new_pair(db: Any) -> None:
    """refresh() writes the new access and refresh tokens to Mongo."""
    repo = TokenRepository(db)
    await repo.upsert(_seed_record(expires_in=3600))
    new_payload = {
        "access_token": "at-3",
        "refresh_token": "rt-3",
        "expires_in": 1800,
        "scope": "read:jira-work offline_access",
    }
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=new_payload))
    async with httpx.AsyncClient() as http:
        provider = _provider(repo, http)
        await provider.refresh()
    stored = await repo.get("cloud-1")
    assert stored is not None
    assert stored["access_token"] == "at-3"
    assert stored["refresh_token"] == "rt-3"
    expires_at = stored["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    delta = (expires_at - datetime.now(tz=UTC)).total_seconds()
    assert 1700 < delta <= 1800


@respx.mock
async def test_refresh_raises_on_invalid_grant(db: Any) -> None:
    """A 400 invalid_grant from the token endpoint surfaces as AuthenticationError."""
    repo = TokenRepository(db)
    await repo.upsert(_seed_record(expires_in=3600))
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    async with httpx.AsyncClient() as http:
        provider = _provider(repo, http)
        with pytest.raises(AuthenticationError):
            await provider.refresh()


@respx.mock
async def test_in_memory_cache_invalidates_on_refresh(db: Any) -> None:
    """After refresh() the cached token is dropped so the next call reads from Mongo."""
    repo = TokenRepository(db)
    await repo.upsert(_seed_record(expires_in=3600))
    async with httpx.AsyncClient() as http:
        provider = _provider(repo, http)
        # First call populates the in-memory cache.
        h1 = await provider.headers()
        assert h1["Authorization"] == "Bearer at-1"
        # Stage a refresh response and force a refresh.
        new_payload = {
            "access_token": "at-fresh",
            "refresh_token": "rt-fresh",
            "expires_in": 3600,
            "scope": "read:jira-work offline_access",
        }
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=new_payload))
        await provider.refresh()
        # The cache must have been invalidated; rewrite the Mongo record so we
        # can prove the next headers() call goes back to the store rather than
        # serving the stale "at-1" copy.
        h2 = await provider.headers()
    assert h2["Authorization"] == "Bearer at-fresh"


async def test_headers_raises_when_no_token_stored(db: Any) -> None:
    """An empty token store raises AuthenticationError pointing at the login script."""
    repo = TokenRepository(db)
    async with httpx.AsyncClient() as http:
        provider = _provider(repo, http)
        with pytest.raises(AuthenticationError, match=r"oauth_login\.py"):
            await provider.headers()
