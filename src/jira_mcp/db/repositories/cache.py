"""Cache repository.

The `cache` collection holds short-lived response payloads keyed by an opaque
string. MongoDB's TTL monitor reaps expired documents lazily, on a roughly
sixty-second sweep, so a document can outlive its `expires_at` for a brief
window. The reader checks `expires_at > now` itself and treats anything past
that point as a miss; this is why we cannot rely on document absence alone.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase


class CacheRepository:
    """Time-bounded key/value cache backed by MongoDB."""

    COLLECTION = "cache"

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        """Bind the repository to a database handle.

        Args:
            db: A Motor database; the collection is resolved lazily.
        """
        self._coll = db[self.COLLECTION]

    async def ensure_indexes(self) -> None:
        """Create the TTL index on ``expires_at``.

        ``_id`` is already unique by default, so we do not declare it again;
        creating it would be a no-op but it adds noise to ``listIndexes``.

        The TTL is configured with ``expireAfterSeconds=0``: each document
        carries its own absolute expiry datetime, and Mongo deletes a doc
        once that timestamp is in the past. This is the standard pattern
        for variable per-document TTL.
        """
        await self._coll.create_index("expires_at", expireAfterSeconds=0)

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return the stored payload, or ``None`` if missing or stale.

        Args:
            key: The cache key.

        Returns:
            The payload dict previously passed to ``set``, or ``None`` when
            the document is absent or its ``expires_at`` is in the past. The
            explicit expiry check exists because Mongo's TTL reaper runs on a
            timer, not synchronously with reads.
        """
        doc = await self._coll.find_one({"_id": key})
        if doc is None:
            return None
        expires_at = doc.get("expires_at")
        if not isinstance(expires_at, datetime):
            return None
        # Mongo strips tzinfo on read in some driver paths; treat naive as UTC.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(tz=UTC):
            return None
        value = doc.get("value")
        if not isinstance(value, dict):
            return None
        return value

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        """Upsert a payload with an absolute expiry.

        Args:
            key: The cache key, used as ``_id``.
            value: The dict to store under ``value``.
            ttl_seconds: How many seconds from now the entry should survive.

        We use ``replace_one(upsert=True)`` rather than ``update_one`` so a
        rewrite does not accidentally merge with stale fields from a prior
        version of the document schema.
        """
        expires_at = datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)
        await self._coll.replace_one(
            {"_id": key},
            {"_id": key, "value": value, "expires_at": expires_at},
            upsert=True,
        )

    async def invalidate(self, key: str) -> None:
        """Delete the document with the given key, if any.

        Args:
            key: The cache key to evict.
        """
        await self._coll.delete_one({"_id": key})

    async def invalidate_prefix(self, prefix: str) -> int:
        """Delete every document whose ``_id`` begins with ``prefix``.

        Args:
            prefix: The literal prefix to match.

        Returns:
            The number of documents removed. The prefix is escaped via a
            regex anchor so callers passing values with regex metacharacters
            do not blow up the query.
        """
        pattern = f"^{re.escape(prefix)}"
        result = await self._coll.delete_many({"_id": {"$regex": pattern}})
        return int(result.deleted_count)
