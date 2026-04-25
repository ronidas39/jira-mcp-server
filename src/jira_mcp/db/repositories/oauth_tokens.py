"""OAuth token repository.

The `oauth_tokens` collection stores the access plus refresh token pair for
each Atlassian Cloud tenant. Records are keyed by ``cloud_id`` (the value
returned from ``/oauth/token/accessible-resources``) so that operators can
``find({"_id": "<cloud-id>"})`` and immediately see the tenant's credentials.

Tokens are stored in clear today; production deployments should encrypt the
``access_token`` and ``refresh_token`` fields at rest before going live.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

from motor.motor_asyncio import AsyncIOMotorDatabase


class TokenRecord(TypedDict):
    """Shape of a stored OAuth token record.

    The ``_id`` field is set equal to ``cloud_id`` so the primary key is the
    tenant identifier. ``expires_at`` is a UTC datetime; callers must compute
    it from the ``expires_in`` value returned by Atlassian's token endpoint.
    """

    _id: str
    cloud_id: str
    access_token: str
    refresh_token: str
    expires_at: datetime
    scopes: str
    updated_at: datetime


class TokenRepository:
    """Persistence for Atlassian OAuth access plus refresh token pairs."""

    COLLECTION = "oauth_tokens"

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        """Bind the repository to a Motor database handle.

        Args:
            db: A Motor database; the collection is resolved lazily.
        """
        self._coll = db[self.COLLECTION]

    @property
    def coll(self) -> Any:
        """Expose the underlying collection for low-cardinality scans.

        The bootstrap needs to enumerate stored tenants without round-tripping
        each through ``get``. Exposing the collection as a read-only property
        keeps that path explicit at the call site (so a reader can grep for
        ``coll`` to find every place that bypasses the repository's API)
        without tempting tools to mutate the collection.
        """
        return self._coll

    async def ensure_indexes(self) -> None:
        """Ensure a unique index on ``cloud_id``.

        ``_id`` is already unique in MongoDB, so we declare a separate unique
        index on ``cloud_id`` only to make accidental schema drift fail fast
        if a future migration ever stops setting ``_id == cloud_id``. The
        method is idempotent: re-running it is a no-op once the index is in
        place.
        """
        await self._coll.create_index("cloud_id", unique=True)

    async def upsert(self, record: TokenRecord) -> None:
        """Insert or replace the token record for a tenant.

        Uses ``replace_one(upsert=True)`` rather than ``update_one`` so a
        rewrite always lands the full document and never merges with stale
        fields from an older schema version. The ``_id`` is set equal to
        ``cloud_id`` so the primary key is human-readable.

        Args:
            record: The full token record to persist.
        """
        doc: dict[str, Any] = dict(record)
        doc["_id"] = record["cloud_id"]
        doc["updated_at"] = datetime.now(tz=UTC)
        await self._coll.replace_one(
            {"_id": record["cloud_id"]},
            doc,
            upsert=True,
        )

    async def get(self, cloud_id: str) -> dict[str, Any] | None:
        """Return the stored record for ``cloud_id`` or ``None`` if absent.

        Args:
            cloud_id: The Atlassian Cloud tenant identifier.

        Returns:
            The raw record dict (including ``_id``) or ``None`` if no record
            is stored for the given tenant. The caller is responsible for
            interpreting the ``expires_at`` field.
        """
        doc = await self._coll.find_one({"_id": cloud_id})
        if doc is None:
            return None
        return dict(doc)

    async def delete(self, cloud_id: str) -> None:
        """Remove the record for ``cloud_id``, if present.

        A missing document is not an error; this matches the operator's
        mental model of "make sure the tenant is logged out".

        Args:
            cloud_id: The Atlassian Cloud tenant identifier.
        """
        await self._coll.delete_one({"_id": cloud_id})


__all__ = ["TokenRecord", "TokenRepository"]
