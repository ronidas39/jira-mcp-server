"""Audit repository unit tests.

Covers FR-901 (record persistence), FR-902 (failover buffer + replay), and
NFR-303 (immutable, append-only invariant).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import PyMongoError

from jira_mcp.db.repositories.audit import AuditRepository

_EXPECTED_KEYS = {
    "ts",
    "tool",
    "input_hash",
    "input_summary",
    "response_status",
    "jira_id",
    "actor",
    "duration_ms",
    "correlation_id",
}


@pytest.fixture
def db() -> Any:
    """Provide an in-memory Motor-compatible database per test."""
    client = AsyncMongoMockClient()
    return client["audit_test_db"]


def _sample_call() -> dict[str, Any]:
    return {
        "tool": "create_issue",
        "input_hash": "deadbeef",
        "input_summary": {"summary": "do the thing"},
        "response_status": "ok",
        "jira_id": "PROJ-1",
        "actor": "user@example.com",
        "duration_ms": 42,
        "correlation_id": "corr-1",
    }


async def test_record_inserts_expected_shape(db: Any) -> None:
    """FR-901: record() persists exactly the documented keys with a UTC ts."""
    repo = AuditRepository(db)
    await repo.record(**_sample_call())

    docs = [d async for d in db["audit_log"].find({})]
    assert len(docs) == 1
    stored = docs[0]
    # _id is added by Mongo; everything else must match the contract exactly.
    stored.pop("_id", None)
    assert set(stored.keys()) == _EXPECTED_KEYS
    ts = stored["ts"]
    assert isinstance(ts, datetime)
    # mongomock returns naive datetimes for the BSON date round-trip; the
    # value we wrote was timezone-aware UTC, so the wall-clock value must
    # be close to "now" regardless of tzinfo presence.
    now = datetime.now(UTC)
    delta = abs((ts.replace(tzinfo=UTC) - now).total_seconds())
    assert delta < 5


async def test_ensure_indexes_creates_three_query_indexes(db: Any) -> None:
    """FR-901: ensure_indexes creates ts, (tool, ts), and (actor, ts) indexes."""
    repo = AuditRepository(db)
    await repo.ensure_indexes()

    names: set[str] = set()
    async for spec in db["audit_log"].list_indexes():
        names.add(spec["name"])
    # _id_ is created by Mongo automatically; we check the three we declared.
    assert "ts_-1" in names
    assert "tool_1_ts_-1" in names
    assert "actor_1_ts_-1" in names


def test_no_update_or_delete_method_on_class() -> None:
    """NFR-303: the class exposes no update_one or delete_one method."""
    assert not hasattr(AuditRepository, "update_one")
    assert not hasattr(AuditRepository, "delete_one")
    # Belt-and-braces: also no update_many or delete_many surface.
    assert not hasattr(AuditRepository, "update_many")
    assert not hasattr(AuditRepository, "delete_many")


async def test_record_writes_buffer_on_mongo_failure(
    db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-902: a Mongo failure during record() lands as a JSONL line in the buffer."""
    buffer_path = tmp_path / "audit-buffer.jsonl"
    repo = AuditRepository(db, buffer_path=buffer_path)

    async def boom(*_a: Any, **_kw: Any) -> None:
        raise PyMongoError("simulated outage")

    monkeypatch.setattr(repo._coll, "insert_one", boom)

    await repo.record(**_sample_call())

    assert buffer_path.exists()
    contents = buffer_path.read_text(encoding="utf-8").splitlines()
    assert len(contents) == 1
    parsed = json.loads(contents[0])
    parsed.pop("_id", None)
    assert set(parsed.keys()) == _EXPECTED_KEYS
    assert parsed["correlation_id"] == "corr-1"


async def test_flush_buffer_replays_and_truncates(
    db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-902: flush_buffer inserts buffered rows and clears the file."""
    buffer_path = tmp_path / "audit-buffer.jsonl"
    repo = AuditRepository(db, buffer_path=buffer_path)

    # Force two records into the buffer by failing inserts.
    async def boom(*_a: Any, **_kw: Any) -> None:
        raise PyMongoError("simulated outage")

    monkeypatch.setattr(repo._coll, "insert_one", boom)
    await repo.record(**_sample_call())
    payload2 = _sample_call()
    payload2["correlation_id"] = "corr-2"
    await repo.record(**payload2)

    # Restore the real collection for replay.
    monkeypatch.undo()

    replayed = await repo.flush_buffer()
    assert replayed == 2

    docs = [d async for d in db["audit_log"].find({})]
    assert len(docs) == 2
    correlation_ids = {d["correlation_id"] for d in docs}
    assert correlation_ids == {"corr-1", "corr-2"}

    # The buffer must be empty after a successful replay.
    assert buffer_path.read_text(encoding="utf-8") == ""


async def test_flush_buffer_returns_zero_when_missing(db: Any, tmp_path: Path) -> None:
    """FR-902: a missing buffer file is not an error; flush_buffer returns 0."""
    repo = AuditRepository(db, buffer_path=tmp_path / "does-not-exist.jsonl")
    assert await repo.flush_buffer() == 0
