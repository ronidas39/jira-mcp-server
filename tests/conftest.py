"""Shared pytest fixtures.

Integration tests are skipped unless `RUN_INTEGRATION=1` is set. The flag is
checked at collection time so a developer can run the unit suite locally
without having a Jira sandbox configured.

This module also provides the test scaffolding for unit tests that exercise
the Jira HTTP client without touching the real Atlassian API: a fixture
loader, a respx-mounted httpx transport, an in-memory MongoDB driver, and a
no-op auth provider.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import respx
from mongomock_motor import AsyncMongoMockClient

from jira_mcp.auth.provider import AuthProvider
from jira_mcp.clients.jira import JiraClient

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "jira"
JIRA_BASE_URL = "https://example.atlassian.net"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip the `integration` mark unless `RUN_INTEGRATION=1`."""
    if os.environ.get("RUN_INTEGRATION") == "1":
        return
    skip_integration = pytest.mark.skip(reason="set RUN_INTEGRATION=1 to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture
def jira_fixture() -> Callable[[str], Any]:
    """Return a loader callable for Jira REST API JSON fixtures.

    The callable accepts a fixture base name (without extension) and returns
    the parsed JSON body. Tests that need to mutate a fixture should call
    the loader twice or copy.deepcopy the result.
    """

    def _load(name: str) -> Any:
        path = FIXTURES_DIR / f"{name}.json"
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    return _load


def _mount_default_routes(router: respx.MockRouter) -> respx.MockRouter:
    """Pre-mount routes that map common Jira endpoints to fixture JSON."""

    def _body(name: str) -> Any:
        with (FIXTURES_DIR / f"{name}.json").open(encoding="utf-8") as handle:
            return json.load(handle)

    router.get(f"{JIRA_BASE_URL}/rest/api/3/issue/PROJ-123").mock(
        return_value=httpx.Response(200, json=_body("issue_PROJ-123"))
    )
    router.get(f"{JIRA_BASE_URL}/rest/api/3/issue/PROJ-123/transitions").mock(
        return_value=httpx.Response(200, json=_body("transitions"))
    )
    router.get(f"{JIRA_BASE_URL}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json=_body("issue_search_response"))
    )
    router.get(f"{JIRA_BASE_URL}/rest/api/3/project/PROJ").mock(
        return_value=httpx.Response(200, json=_body("project_PROJ"))
    )
    router.get(f"{JIRA_BASE_URL}/rest/api/3/project").mock(
        return_value=httpx.Response(200, json=_body("projects_list"))
    )
    router.get(f"{JIRA_BASE_URL}/rest/api/3/users/search").mock(
        return_value=httpx.Response(200, json=_body("users_search"))
    )
    router.get(f"{JIRA_BASE_URL}/rest/agile/1.0/board").mock(
        return_value=httpx.Response(200, json=_body("boards_list"))
    )
    router.get(f"{JIRA_BASE_URL}/rest/agile/1.0/board/7/sprint").mock(
        return_value=httpx.Response(200, json=_body("sprints_list"))
    )
    router.get(f"{JIRA_BASE_URL}/rest/agile/1.0/sprint/42").mock(
        return_value=httpx.Response(200, json=_body("sprint_42"))
    )
    return router


@pytest.fixture
def mock_jira_http() -> AsyncIterator[respx.MockRouter]:
    """Yield a respx Router with default Jira routes mounted.

    Tests can refine or override individual routes by calling the standard
    respx API on the yielded object. The router is bound to the example
    base URL used throughout the fixture data.
    """
    with respx.mock(base_url=JIRA_BASE_URL, assert_all_called=False) as router:
        _mount_default_routes(router)
        yield router


@pytest_asyncio.fixture
async def jira_async_client(
    mock_jira_http: respx.MockRouter,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an httpx.AsyncClient routed through the respx mock transport."""
    async with httpx.AsyncClient(base_url=JIRA_BASE_URL) as client:
        yield client


class _NoopAuth:
    """Auth provider that returns a static Accept header and never refreshes."""

    async def headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    async def refresh(self) -> None:
        return None


@pytest.fixture
def noop_auth() -> AuthProvider:
    """Return a no-op AuthProvider for tests that should not exercise auth."""
    return _NoopAuth()


@pytest.fixture
def jira_client(
    jira_async_client: httpx.AsyncClient,
    noop_auth: AuthProvider,
) -> JiraClient:
    """Return a JiraClient wired to the respx-mocked transport."""
    return JiraClient(
        base_url=JIRA_BASE_URL,
        auth=noop_auth,
        http=jira_async_client,
        max_retries=0,
    )


@pytest.fixture
def mock_mongo_db() -> Any:
    """Return an in-memory AsyncIOMotorDatabase via mongomock_motor."""
    client = AsyncMongoMockClient()
    return client["jira_mcp_test"]
