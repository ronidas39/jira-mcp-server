"""``/sprint-review`` prompt: scaffold a sprint retrospective.

The prompt directs the model to pull the sprint report and per-assignee
workload, then produce a retrospective markdown grouped into goals, what
shipped, what slipped, and a question to the user about carry-over.
"""

from __future__ import annotations

from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent

NAME = "sprint-review"

DEFINITION = Prompt(
    name=NAME,
    description=(
        "Draft a sprint retrospective for a board. Pulls the sprint report "
        "and workload split, then formats a markdown summary with sections "
        "for goals, shipped, slipped, and carry-over."
    ),
    arguments=[
        PromptArgument(
            name="board_id",
            description="Numeric Jira board id to review.",
            required=True,
        ),
        PromptArgument(
            name="sprint_id",
            description=(
                "Optional numeric sprint id. When omitted, use the active "
                "sprint of the given board."
            ),
            required=False,
        ),
    ],
)


def _body(board_id: str, sprint_id: str | None) -> str:
    """Return the user-facing instruction body for the prompt."""
    sprint_clause = (
        f"sprint id {sprint_id}"
        if sprint_id
        else (
            "the active sprint of the board (resolve it first by calling "
            "the active_sprint or list_sprints tool with state='active')"
        )
    )
    return (
        f"Produce a sprint retrospective for board id {board_id}, "
        f"covering {sprint_clause}.\n\n"
        "Steps, in order:\n"
        "1. Call the sprint_report tool with the resolved sprint id.\n"
        "2. Call the workload_by_assignee tool for the same sprint.\n"
        "3. Format a markdown document with these sections:\n"
        "   - ## Goals (the sprint goal verbatim, plus a one line read on "
        "whether it was met)\n"
        "   - ## What shipped (issues moved to Done, grouped by assignee)\n"
        "   - ## What slipped (issues still open, grouped by status, with a "
        "short reason if a comment in the last 48 hours explains it)\n"
        "   - ## Carry-over question (ask the user which slipped issues "
        "should roll into the next sprint)\n\n"
        "Rules:\n"
        "- Do not call any write tool. This prompt is read-only.\n"
        "- Do not invent issue keys; quote only what the tools returned.\n"
        "- Keep the document under 400 lines."
    )


async def render(arguments: dict[str, str] | None) -> GetPromptResult:
    """Render the ``/sprint-review`` prompt for the given arguments.

    Args:
        arguments: Mapping of argument names to string values from the MCP
            client. ``board_id`` is required; ``sprint_id`` is optional.

    Returns:
        A ``GetPromptResult`` with one user message ready to be played into
        the model.

    Raises:
        ValueError: If ``board_id`` is missing.
    """
    args = arguments or {}
    board_id = args.get("board_id")
    if not board_id:
        msg = "sprint-review requires board_id"
        raise ValueError(msg)
    sprint_id = args.get("sprint_id")
    text = _body(board_id, sprint_id)
    return GetPromptResult(
        description=DEFINITION.description,
        messages=[
            PromptMessage(role="user", content=TextContent(type="text", text=text)),
        ],
    )


__all__ = ["DEFINITION", "NAME", "render"]
