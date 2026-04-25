"""Audit repository.

The `audit_log` collection is append-only by policy (NFR-303). The repository
exposes only `record(...)`; there is no update or delete method on this class
on purpose, so a misclick at the call site cannot turn into a compliance
incident. If a record needs to be retracted, that is a reversal record, not a
mutation of an existing one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase


class AuditRepository:
    """Immutable, append-only audit log."""

    COLLECTION = "audit_log"

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._coll = db[self.COLLECTION]

    async def ensure_indexes(self) -> None:
        """Indexes covering the common query shapes (recent activity, by tool, by actor)."""
        await self._coll.create_index([("ts", -1)])
        await self._coll.create_index([("tool", 1), ("ts", -1)])
        await self._coll.create_index([("actor", 1), ("ts", -1)])

    async def record(
        self,
        *,
        tool: str,
        input_hash: str,
        input_summary: dict[str, Any],
        response_status: str,
        jira_id: str | None,
        actor: str,
        duration_ms: int,
        correlation_id: str,
    ) -> None:
        """Insert one audit record. Never updates or deletes."""
        await self._coll.insert_one(
            {
                "ts": datetime.now(timezone.utc),
                "tool": tool,
                "input_hash": input_hash,
                "input_summary": input_summary,
                "response_status": response_status,
                "jira_id": jira_id,
                "actor": actor,
                "duration_ms": duration_ms,
                "correlation_id": correlation_id,
            }
        )
