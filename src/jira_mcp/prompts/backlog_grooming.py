"""``/backlog-grooming`` prompt: triage stale backlog items.

The prompt instructs the model to pull stale issues older than 30 days,
group them by status and priority, and propose archive vs reprioritize
candidates. No write happens without explicit user confirmation.
"""

from __future__ import annotations

from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent

NAME = "backlog-grooming"

DEFINITION = Prompt(
    name=NAME,
    description=(
        "Walk a project's stale backlog, group items by status and priority, "
        "and propose archive or reprioritize candidates. Asks the user "
        "before any write."
    ),
    arguments=[
        PromptArgument(
            name="project_key",
            description="Jira project key to groom (e.g. PROJ).",
            required=True,
        ),
    ],
)


def _body(project_key: str) -> str:
    """Return the user-facing instruction body for the prompt."""
    return (
        f"Help groom the backlog for project {project_key}.\n\n"
        "Steps, in order:\n"
        "1. Call the stale_issues tool with project_key="
        f"{project_key} and days=30.\n"
        "2. Group the returned issues first by status, then by priority "
        "inside each status bucket.\n"
        "3. For each issue, classify it as one of:\n"
        "   - archive candidate: no activity in 30+ days, no assignee, "
        "low or unset priority\n"
        "   - reprioritize candidate: still relevant but stale "
        "(suggest a new priority and a reason)\n"
        "   - keep: explicitly say why it should stay untouched\n"
        "4. Render the result as markdown with one heading per status and a "
        "table per priority bucket (key, summary, age, recommendation).\n"
        "5. Stop and ask the user: 'Confirm which archive and reprioritize "
        "actions to apply.' Do not call any write tool until the user "
        "lists the keys to act on.\n\n"
        "Rules:\n"
        "- Read-only until confirmation.\n"
        "- Never auto-close, never auto-change priority without an "
        "explicit go-ahead from the user.\n"
        "- Do not invent issue keys."
    )


async def render(arguments: dict[str, str] | None) -> GetPromptResult:
    """Render the ``/backlog-grooming`` prompt for the given arguments.

    Args:
        arguments: Mapping of argument names to string values. ``project_key``
            is required.

    Returns:
        A ``GetPromptResult`` with one user message.

    Raises:
        ValueError: If ``project_key`` is missing.
    """
    args = arguments or {}
    project_key = args.get("project_key")
    if not project_key:
        msg = "backlog-grooming requires project_key"
        raise ValueError(msg)
    text = _body(project_key)
    return GetPromptResult(
        description=DEFINITION.description,
        messages=[
            PromptMessage(role="user", content=TextContent(type="text", text=text)),
        ],
    )


__all__ = ["DEFINITION", "NAME", "render"]
