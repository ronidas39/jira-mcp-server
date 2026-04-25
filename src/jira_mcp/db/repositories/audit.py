"""Audit repository.

The `audit_log` collection is append-only by policy (NFR-303). The repository
exposes only `record(...)`; there is no update or delete method on this class
on purpose, so a misclick at the call site cannot turn into a compliance
incident. If a record needs to be retracted, that is a reversal record, not a
mutation of an existing one.

If the primary insert fails because Mongo is unreachable, the record is
appended to a local JSONL buffer file so the audit chain is not lost. A
later call to ``flush_buffer()`` replays the buffer once the database is
healthy again.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles
import structlog
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

_log = structlog.get_logger(__name__)

# Replay batch size kept modest so a partial outage does not produce a single
# multi-megabyte insert that itself trips the server's request size limits.
_REPLAY_BATCH_SIZE = 500


class AuditRepository:
    """Immutable, append-only audit log."""

    COLLECTION = "audit_log"
    BUFFER_PATH = Path(".audit-buffer.jsonl")

    def __init__(
        self,
        db: AsyncIOMotorDatabase[Any],
        *,
        buffer_path: Path | None = None,
    ) -> None:
        """Bind the repository and optionally override the failover buffer path.

        Args:
            db: Motor database handle.
            buffer_path: Optional override for the JSONL failover file. Tests
                point this at a ``tmp_path`` so they do not pollute the
                project root.
        """
        self._coll = db[self.COLLECTION]
        self._buffer_path: Path = buffer_path if buffer_path is not None else self.BUFFER_PATH

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
        """Insert one audit record. Never updates or deletes.

        On any ``PyMongoError`` the document is appended to the failover
        buffer instead of being dropped: losing an audit row silently is
        worse than the latency hit of a disk write, and the buffer can be
        replayed by ``flush_buffer`` once the database recovers.
        """
        doc: dict[str, Any] = {
            "ts": datetime.now(UTC),
            "tool": tool,
            "input_hash": input_hash,
            "input_summary": input_summary,
            "response_status": response_status,
            "jira_id": jira_id,
            "actor": actor,
            "duration_ms": duration_ms,
            "correlation_id": correlation_id,
        }
        try:
            await self._coll.insert_one(doc)
        except PyMongoError as exc:
            await self._append_to_buffer(doc)
            _log.warning(
                "audit.record.buffered",
                error=str(exc),
                buffer_path=str(self._buffer_path),
            )

    async def _append_to_buffer(self, doc: dict[str, Any]) -> None:
        """Append one JSONL line to the failover buffer.

        ``json.dumps(default=str)`` handles the ``datetime`` field without
        needing a custom encoder; the inverse path in ``flush_buffer`` parses
        the string back into a ``datetime`` so Mongo stores it as a BSON date
        on replay.
        """
        line = json.dumps(doc, default=str)
        async with aiofiles.open(self._buffer_path, mode="a", encoding="utf-8") as fh:
            await fh.write(line + "\n")

    async def flush_buffer(self) -> int:
        """Replay buffered audit rows into Mongo and truncate the buffer.

        Returns:
            The number of rows replayed. Returns ``0`` when the buffer file
            is missing.

        Bad lines are skipped, not fatal: a single corrupt row should not
        block the rest of the chain. Each skipped line is logged so the
        operator can investigate. The file is truncated only after a fully
        successful insert pass, so a crash mid-replay leaves the buffer
        intact and a future call retries the same rows. This makes replays
        at-least-once; the audit consumer must therefore tolerate duplicate
        ``correlation_id`` values across rows.
        """
        if not self._buffer_path.exists():
            return 0

        async with aiofiles.open(self._buffer_path, encoding="utf-8") as fh:
            raw = await fh.read()

        docs: list[dict[str, Any]] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                _log.warning("audit.replay.skipped", line=line, error=str(exc))
                continue
            ts_val = parsed.get("ts")
            if isinstance(ts_val, str):
                try:
                    parsed["ts"] = datetime.fromisoformat(ts_val)
                except ValueError:
                    _log.warning("audit.replay.skipped", line=line, error="bad ts")
                    continue
            docs.append(parsed)

        replayed = 0
        for start in range(0, len(docs), _REPLAY_BATCH_SIZE):
            batch = docs[start : start + _REPLAY_BATCH_SIZE]
            if not batch:
                continue
            await self._coll.insert_many(batch)
            replayed += len(batch)

        # Truncate only after every batch has landed so a crash mid-replay
        # does not vanish unreplayed rows.
        async with aiofiles.open(self._buffer_path, mode="w", encoding="utf-8") as fh:
            await fh.write("")

        return replayed
