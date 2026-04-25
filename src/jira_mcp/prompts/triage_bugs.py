"""``/triage-bugs`` prompt: bring open bugs into a coherent priority order.

The prompt steers the model to search open bugs in a project, group them
by priority, suggest priority changes for unset items, and stop for user
confirmation before any mutation.
"""

from __future__ import annotations

from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent

NAME = "triage-bugs"

DEFINITION = Prompt(
    name=NAME,
    description=(
        "Triage open bugs in a project. Groups by priority, suggests "
        "priority changes for unset items, and asks the user before "
        "applying any change."
    ),
    arguments=[
        PromptArgument(
            name="project_key",
            description="Jira project key to triage (e.g. PROJ).",
            required=True,
        ),
    ],
)


def _body(project_key: str) -> str:
    """Return the user-facing instruction body for the prompt."""
    jql = f'project = "{project_key}" AND issuetype = Bug AND status = Open'
    return (
        f"Run a bug triage pass on project {project_key}.\n\n"
        "Steps, in order:\n"
        f"1. Call the search_issues tool with jql: {jql}\n"
        "2. Group the returned bugs by priority. For any bug whose "
        "priority is null, None, or 'Undefined', propose a priority "
        "(Highest, High, Medium, Low) using these signals:\n"
        "   - reporter activity in the last 7 days\n"
        "   - labels containing 'crash', 'security', or 'data-loss' imply "
        "Highest\n"
        "   - issues older than 90 days with no comment imply Low\n"
        "3. Render the result as a markdown table per priority bucket: "
        "key, summary, current priority, suggested priority, reason.\n"
        "4. Stop and ask the user: 'Which priority changes should I "
        "apply?' Do not call set_priority, transition, or any other "
        "write tool until the user names specific keys.\n\n"
        "Rules:\n"
        "- Read-only until confirmation.\n"
        "- Never close a bug as part of triage.\n"
        "- Do not invent issue keys; only act on what the search returned."
    )


async def render(arguments: dict[str, str] | None) -> GetPromptResult:
    """Render the ``/triage-bugs`` prompt for the given arguments.

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
        msg = "triage-bugs requires project_key"
        raise ValueError(msg)
    text = _body(project_key)
    return GetPromptResult(
        description=DEFINITION.description,
        messages=[
            PromptMessage(role="user", content=TextContent(type="text", text=text)),
        ],
    )


__all__ = ["DEFINITION", "NAME", "render"]
