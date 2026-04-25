"""MCP resource handlers exposed by the Jira MCP server.

Resources are read-only views of Jira data addressed by URI. The package
keeps registration logic in ``jira_resources`` and re-exports the single
``register`` entry point used by the server bootstrap.
"""

from __future__ import annotations

from .jira_resources import register

__all__ = ["register"]
