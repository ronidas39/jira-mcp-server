"""Shared pytest fixtures.

Integration tests are skipped unless `RUN_INTEGRATION=1` is set. The flag is
checked at collection time so a developer can run the unit suite locally
without having a Jira sandbox configured.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip the `integration` mark unless `RUN_INTEGRATION=1`."""
    if os.environ.get("RUN_INTEGRATION") == "1":
        return
    skip_integration = pytest.mark.skip(reason="set RUN_INTEGRATION=1 to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
