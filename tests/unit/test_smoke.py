"""Smoke tests for the test scaffolding.

These verify pytest, asyncio mode, and the package import path are wired
correctly. They will be replaced as real unit tests come online.
"""

from __future__ import annotations

import asyncio

import jira_mcp


def test_package_imports() -> None:
    """Smoke: package imports cleanly."""
    assert jira_mcp.__version__


async def test_async_harness_works() -> None:
    """Smoke: pytest-asyncio is configured."""
    await asyncio.sleep(0)
    assert True
