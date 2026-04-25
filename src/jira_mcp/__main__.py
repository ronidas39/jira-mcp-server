"""Process entry point.

Usage:
    python -m jira_mcp

Composes the application, runs startup checks, hands control to the
selected transport, and tears down cleanly on exit. Startup failures are
logged as a single `startup.failed` event and the process exits 1; a
keyboard interrupt exits 130 to follow the convention POSIX shells use
for signal-terminated processes.
"""

from __future__ import annotations

import asyncio
import sys


async def _run() -> int:
    """Async main. Returns the exit code the wrapper should pass to `sys.exit`.

    Imports are lazy so `--help`-style cold paths do not pay the cost of
    pulling Mongo, httpx, and the MCP SDK into memory.
    """
    from .config import load_settings  # noqa: PLC0415  (lazy: cheap --help)
    from .server import create_app, run, shutdown, startup  # noqa: PLC0415
    from .utils.logging import get_logger  # noqa: PLC0415

    try:
        settings = load_settings()
    except Exception as exc:
        # Logging may not be configured yet, so fall back to stderr.
        print(f"startup.failed: settings load: {exc}", file=sys.stderr)
        return 1

    log = get_logger("jira_mcp")

    try:
        ctx = create_app(settings)
    except Exception as exc:
        log.error("startup.failed", stage="create_app", error=str(exc))
        return 1

    try:
        await startup(ctx)
    except Exception as exc:
        log.error("startup.failed", stage="startup", error=str(exc))
        await shutdown(ctx)
        return 1

    try:
        await run(ctx, settings)
        return 0
    except Exception as exc:
        log.error("server.crashed", error=str(exc))
        return 1
    finally:
        await shutdown(ctx)


def main() -> None:
    """Synchronous entry point exposed via `pyproject.toml [project.scripts]`."""
    try:
        code = asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(130)
    sys.exit(code)


if __name__ == "__main__":
    main()
