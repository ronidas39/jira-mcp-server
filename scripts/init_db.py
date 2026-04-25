"""Initialise the MongoDB database for the Jira MCP server.

Idempotent: safe to re-run. Creates the `audit_log` collection (immutable,
append-only per FR-901 and NFR-303) and the `cache` collection (with a TTL
index on `expires_at`).

Sync pymongo is used here on purpose: this is a one-shot operator utility,
not in the async request path. The TLS CA bundle is sourced from `certifi`
so the script works against MongoDB Atlas on macOS Python.org builds without
any extra environment plumbing.

Usage:
    python scripts/init_db.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import certifi
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import CollectionInvalid


def _load_env() -> tuple[str, str]:
    """Read `MONGO_URI` and `MONGO_DB` from `.env` without depending on the package."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    values: dict[str, str] = {}
    if env_path.exists():
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip()
    uri = os.environ.get("MONGO_URI") or values.get("MONGO_URI", "")
    db = os.environ.get("MONGO_DB") or values.get("MONGO_DB", "jira_mcp")
    if not uri:
        sys.exit("MONGO_URI is not set (check .env)")
    return uri, db


def main() -> None:
    uri, db_name = _load_env()
    client: MongoClient = MongoClient(
        uri,
        serverSelectionTimeoutMS=10_000,
        tlsCAFile=certifi.where(),
    )

    client.admin.command("ping")
    print(f"connected to cluster, using database: {db_name}")

    db = client[db_name]

    for name in ("audit_log", "cache"):
        try:
            db.create_collection(name)
            print(f"created collection: {name}")
        except CollectionInvalid:
            print(f"collection already exists: {name}")

    audit = db["audit_log"]
    audit.create_index([("ts", DESCENDING)])
    audit.create_index([("tool", ASCENDING), ("ts", DESCENDING)])
    audit.create_index([("actor", ASCENDING), ("ts", DESCENDING)])
    print("audit_log indexes ensured")

    cache = db["cache"]
    cache.create_index([("key", ASCENDING)], unique=True)
    cache.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
    print("cache indexes ensured (TTL on expires_at)")

    print("collections:", sorted(db.list_collection_names()))
    client.close()


if __name__ == "__main__":
    main()
