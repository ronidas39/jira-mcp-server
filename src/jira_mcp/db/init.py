"""Database bootstrap helpers.

A single entry point for bringing every collection's indexes online. The
server calls this from its lifespan hook so a fresh deployment is ready to
serve before the first request lands.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from jira_mcp.db.repositories.audit import AuditRepository
from jira_mcp.db.repositories.cache import CacheRepository


async def ensure_all_indexes(db: AsyncIOMotorDatabase[Any]) -> None:
    """Create every collection index used by the server.

    Args:
        db: A Motor database handle.

    Calls each repository's ``ensure_indexes`` in sequence rather than in
    parallel: the operations are cheap, idempotent, and serial output makes
    a startup failure easier to attribute to one collection.
    """
    audit = AuditRepository(db)
    cache = CacheRepository(db)
    await audit.ensure_indexes()
    await cache.ensure_indexes()
