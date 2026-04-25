"""Smoke tests for the test scaffolding.

These verify pytest, asyncio mode, and the package import path are wired
correctly. They will be replaced as real unit tests come online.
"""

from __future__ import annotations


def test_package_imports() -> None:
    """Smoke: package imports cleanly."""
    import jira_mcp

    assert jira_mcp.__version__


async def test_async_harness_works() -> None:
    """Smoke: pytest-asyncio is configured."""
    import asyncio

    await asyncio.sleep(0)
    assert True
