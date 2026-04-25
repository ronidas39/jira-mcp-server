"""MongoDB connection helper.

Wraps a single Motor client plus database handle. The client is lazy; we do
not open a socket until somebody actually asks for the database. That keeps
import-time side effects out of the test suite.

Atlas connections from macOS Python.org builds need the `certifi` CA bundle
explicitly. We pass it on every call to keep the client portable across
container images and developer laptops without extra environment plumbing.
"""

from __future__ import annotations

from typing import Any

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


class MongoConnection:
    """Holds a single Motor client plus a database handle."""

    def __init__(self, uri: str, db_name: str) -> None:
        self._client: AsyncIOMotorClient[Any] | None = None
        self._uri = uri
        self._db_name = db_name

    @property
    def client(self) -> AsyncIOMotorClient[Any]:
        if self._client is None:
            self._client = AsyncIOMotorClient[Any](self._uri, **self._tls_kwargs())
        return self._client

    def _tls_kwargs(self) -> dict[str, Any]:
        """Return TLS kwargs only when the URI implies a TLS connection.

        Atlas (``mongodb+srv://``) negotiates TLS by default and needs the
        certifi bundle on macOS Python.org builds. Plain local mongo runs
        do not speak TLS at all, and passing ``tlsCAFile`` to pymongo
        implicitly enables TLS, which then handshake-fails against the
        plaintext server. Gating on the URI shape keeps both deployments
        working with one helper.
        """
        if self._uri.startswith("mongodb+srv://") or "tls=true" in self._uri:
            return {"tlsCAFile": certifi.where()}
        return {}

    @property
    def db(self) -> AsyncIOMotorDatabase[Any]:
        return self.client[self._db_name]

    async def ping(self) -> None:
        """Verify connectivity. Raises on failure."""
        await self.client.admin.command("ping")

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
