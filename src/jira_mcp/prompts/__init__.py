"""MCP prompt templates exposed by the Jira MCP server.

Each prompt module owns its own ``DEFINITION`` (a ``Prompt`` object) and an
async ``render`` callable. This package's ``register`` entry point wires
them onto the MCP ``Server`` via ``@server.list_prompts`` and
``@server.get_prompt``.
"""

from __future__ import annotations

from typing import Any

from mcp.server import Server
from mcp.types import GetPromptResult, Prompt

from . import backlog_grooming, sprint_review, standup_summary, triage_bugs

# Module-keyed registry: name -> (definition, render). Centralized so adding
# a new prompt is a one-line edit and the server bootstrap stays generic.
_REGISTRY = {
    sprint_review.NAME: (sprint_review.DEFINITION, sprint_review.render),
    backlog_grooming.NAME: (backlog_grooming.DEFINITION, backlog_grooming.render),
    triage_bugs.NAME: (triage_bugs.DEFINITION, triage_bugs.render),
    standup_summary.NAME: (standup_summary.DEFINITION, standup_summary.render),
}


def all_prompts() -> list[Prompt]:
    """Return the static list of prompt definitions for ``list_prompts``."""
    return [definition for definition, _ in _REGISTRY.values()]


async def render_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    """Dispatch a ``get_prompt`` call to the matching render function.

    Args:
        name: The prompt name requested by the MCP client.
        arguments: Optional argument mapping forwarded to the renderer.

    Returns:
        The rendered ``GetPromptResult``.

    Raises:
        ValueError: If ``name`` is not a registered prompt.
    """
    entry = _REGISTRY.get(name)
    if entry is None:
        msg = f"unknown prompt: {name!r}"
        raise ValueError(msg)
    _, render = entry
    return await render(arguments)


def register(server: Server, ctx: Any) -> None:
    """Wire prompt handlers onto the MCP ``Server`` instance.

    Args:
        server: The MCP server to register handlers on.
        ctx: The server context. Currently unused by prompt rendering, but
            kept on the signature so the server bootstrap can pass the same
            ctx object to tools, resources, and prompts uniformly.
    """
    del ctx  # Reserved for future prompts that read settings or DB state.

    @server.list_prompts()
    async def _list_prompts() -> list[Prompt]:
        """Return every prompt this server publishes."""
        return all_prompts()

    @server.get_prompt()
    async def _get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
        """Render the prompt requested by the client."""
        return await render_prompt(name, arguments)


__all__ = ["all_prompts", "register", "render_prompt"]
