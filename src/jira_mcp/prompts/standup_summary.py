"""``/standup-summary`` prompt: a 24-hour digest grouped by assignee.

The prompt instructs the model to search issues updated in the last 24
hours within a project and produce a markdown digest grouped by assignee
so a standup host can read it line by line.
"""

from __future__ import annotations

from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent

NAME = "standup-summary"

DEFINITION = Prompt(
    name=NAME,
    description=(
        "Produce a 24-hour standup digest for a project, grouped by "
        "assignee. Read-only."
    ),
    arguments=[
        PromptArgument(
            name="project_key",
            description="Jira project key to summarize (e.g. PROJ).",
            required=True,
        ),
    ],
)


def _body(project_key: str) -> str:
    """Return the user-facing instruction body for the prompt."""
    jql = f'project = "{project_key}" AND updated >= -1d ORDER BY assignee, updated DESC'
    return (
        f"Generate a standup digest for project {project_key}.\n\n"
        "Steps, in order:\n"
        f"1. Call the search_issues tool with jql: {jql}\n"
        "2. Group the returned issues by assignee. Unassigned issues "
        "land in a final 'Unassigned' section.\n"
        "3. For each assignee, list their issues as bullet points: "
        "key, status, summary, and a short note (one line) on what "
        "changed in the last 24 hours, drawn from the issue's most "
        "recent comment if one exists in that window.\n"
        "4. Add a one-line top-of-page header: project key, the date in "
        "ISO format, and the total number of issues in the digest.\n\n"
        "Rules:\n"
        "- Read-only. Do not call any write tool.\n"
        "- Do not invent issue keys, comments, or assignees.\n"
        "- Keep each bullet under 200 characters."
    )


async def render(arguments: dict[str, str] | None) -> GetPromptResult:
    """Render the ``/standup-summary`` prompt for the given arguments.

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
        msg = "standup-summary requires project_key"
        raise ValueError(msg)
    text = _body(project_key)
    return GetPromptResult(
        description=DEFINITION.description,
        messages=[
            PromptMessage(role="user", content=TextContent(type="text", text=text)),
        ],
    )


__all__ = ["DEFINITION", "NAME", "render"]
