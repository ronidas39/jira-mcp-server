"""Process entry point.

Usage:
    python -m jira_mcp

The async `_run` helper performs settings load, structured logger
initialisation, transport selection, and finally hands off to the MCP
SDK's serve loop. The transport choice comes from `MCP_TRANSPORT`
(`stdio` by default, `http` when running behind a reverse proxy).
"""

from __future__ import annotations

import asyncio
import sys


async def _run() -> None:
    """Async main. Wired up incrementally as milestones land."""
    # Lazy import keeps cold-start light when only `--help` is invoked.
    from config import load_settings

    settings = load_settings()
    # The structured logger and the actual MCP server come online in M1.
    print(
        f"jira-mcp-server starting (transport={settings.mcp_transport})",
        file=sys.stderr,
    )


def main() -> None:
    """Synchronous entry point exposed via `pyproject.toml [project.scripts]`."""
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
