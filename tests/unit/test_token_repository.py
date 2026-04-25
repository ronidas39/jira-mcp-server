"""Token repository unit tests.

Covers the documented schema of the ``oauth_tokens`` collection: the
primary key is ``cloud_id``, ``upsert`` is idempotent, ``get`` returns
``None`` for misses, ``delete`` is a silent no-op for missing keys, and
``ensure_indexes`` is safe to re-run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from mongomock_motor import AsyncMongoMockClient

from jira_mcp.db.repositories.oauth_tokens import TokenRecord, TokenRepository


@pytest.fixture
def db() -> Any:
    """Return a fresh in-memory Motor-compatible database per test."""
    client = AsyncMongoMockClient()
    return client["token_test_db"]


def _record(cloud_id: str = "cid-1") -> TokenRecord:
    """Return a ready-to-insert token record for tests."""
    now = datetime.now(tz=UTC)
    return TokenRecord(
        _id=cloud_id,
        cloud_id=cloud_id,
        access_token="at-1",
        refresh_token="rt-1",
        expires_at=now + timedelta(seconds=3600),
        scopes="read:jira-work offline_access",
        updated_at=now,
    )


async def test_upsert_creates_record_keyed_by_cloud_id(db: Any) -> None:
    """upsert() persists a record whose _id equals its cloud_id."""
    repo = TokenRepository(db)
    await repo.upsert(_record("acme"))
    doc = await db["oauth_tokens"].find_one({"_id": "acme"})
    assert doc is not None
    assert doc["cloud_id"] == "acme"
    assert doc["access_token"] == "at-1"
    assert doc["refresh_token"] == "rt-1"
    assert doc["scopes"] == "read:jira-work offline_access"
    assert isinstance(doc["expires_at"], datetime)


async def test_upsert_replaces_existing_record(db: Any) -> None:
    """A second upsert overwrites the previous tokens for the same tenant."""
    repo = TokenRepository(db)
    await repo.upsert(_record("acme"))

    refreshed = _record("acme")
    refreshed["access_token"] = "at-2"
    refreshed["refresh_token"] = "rt-2"
    await repo.upsert(refreshed)

    doc = await db["oauth_tokens"].find_one({"_id": "acme"})
    assert doc is not None
    assert doc["access_token"] == "at-2"
    assert doc["refresh_token"] == "rt-2"

    count = await db["oauth_tokens"].count_documents({})
    assert count == 1


async def test_get_returns_none_for_unknown_cloud_id(db: Any) -> None:
    """get() returns None when the record is missing."""
    repo = TokenRepository(db)
    assert await repo.get("missing") is None


async def test_get_returns_stored_record(db: Any) -> None:
    """get() returns the dict that was upserted."""
    repo = TokenRepository(db)
    await repo.upsert(_record("acme"))
    fetched = await repo.get("acme")
    assert fetched is not None
    assert fetched["cloud_id"] == "acme"
    assert fetched["access_token"] == "at-1"


async def test_delete_removes_record(db: Any) -> None:
    """delete() removes the document and is a no-op on the second call."""
    repo = TokenRepository(db)
    await repo.upsert(_record("acme"))
    await repo.delete("acme")
    assert await repo.get("acme") is None
    # idempotent: a second delete on a missing record does not raise.
    await repo.delete("acme")


async def test_ensure_indexes_is_idempotent(db: Any) -> None:
    """ensure_indexes() can be re-run without error and creates cloud_id index."""
    repo = TokenRepository(db)
    await repo.ensure_indexes()
    await repo.ensure_indexes()  # second call must not raise.
    names: set[str] = set()
    async for spec in db["oauth_tokens"].list_indexes():
        names.add(spec["name"])
    assert "cloud_id_1" in names
