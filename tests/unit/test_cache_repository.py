"""Cache repository unit tests.

Covers FR-903 (TTL-bounded key/value cache: round-trip, expiry, invalidation,
prefix invalidation, idempotent index creation).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from mongomock_motor import AsyncMongoMockClient

from jira_mcp.db.repositories.cache import CacheRepository


@pytest.fixture
def db() -> Any:
    """Provide an in-memory Motor-compatible database per test."""
    client = AsyncMongoMockClient()
    return client["cache_test_db"]


async def test_set_then_get_round_trip(db: Any) -> None:
    """FR-903: a value written via set() is returned verbatim by get()."""
    repo = CacheRepository(db)
    payload = {"answer": 42, "nested": {"k": "v"}}
    await repo.set("k1", payload, ttl_seconds=60)

    got = await repo.get("k1")
    assert got == payload


async def test_get_returns_none_when_expired(db: Any) -> None:
    """FR-903: a document whose expires_at is in the past is treated as a miss.

    Mongo's TTL reaper is lazy, so the document can still be there; the read
    path explicitly checks ``expires_at`` to avoid serving stale data.
    """
    repo = CacheRepository(db)
    past = datetime.now(tz=UTC) - timedelta(seconds=30)
    await db["cache"].replace_one(
        {"_id": "stale"},
        {"_id": "stale", "value": {"v": 1}, "expires_at": past},
        upsert=True,
    )

    assert await repo.get("stale") is None


async def test_invalidate_removes_document(db: Any) -> None:
    """FR-903: invalidate(key) removes the document from the collection."""
    repo = CacheRepository(db)
    await repo.set("k1", {"v": 1}, ttl_seconds=60)
    await repo.invalidate("k1")
    assert await repo.get("k1") is None
    assert await db["cache"].find_one({"_id": "k1"}) is None


async def test_invalidate_prefix_only_removes_matching_keys(db: Any) -> None:
    """FR-903: invalidate_prefix removes only the matching keys and counts them."""
    repo = CacheRepository(db)
    await repo.set("issue:PROJ-1", {"v": 1}, ttl_seconds=60)
    await repo.set("issue:PROJ-2", {"v": 2}, ttl_seconds=60)
    await repo.set("sprint:42", {"v": 3}, ttl_seconds=60)

    removed = await repo.invalidate_prefix("issue:")
    assert removed == 2
    assert await repo.get("issue:PROJ-1") is None
    assert await repo.get("issue:PROJ-2") is None
    assert await repo.get("sprint:42") == {"v": 3}


async def test_ensure_indexes_is_idempotent(db: Any) -> None:
    """FR-903: ensure_indexes can be called twice without raising."""
    repo = CacheRepository(db)
    await repo.ensure_indexes()
    await repo.ensure_indexes()

    names: set[str] = set()
    async for spec in db["cache"].list_indexes():
        names.add(spec["name"])
    assert "expires_at_1" in names
