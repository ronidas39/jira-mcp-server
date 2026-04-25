"""Unit tests for the Jira MCP prompt templates.

The tests do not stand up the full server. They reach into each prompt
module's ``DEFINITION`` (a ``Prompt`` object) and ``render`` callable to
verify the public surface: name, required arguments, and that rendering
with the documented arguments yields a non-empty user message.
"""

from __future__ import annotations

import pytest

from jira_mcp.prompts import (
    all_prompts,
    backlog_grooming,
    render_prompt,
    sprint_review,
    standup_summary,
    triage_bugs,
)


def _required_args(definition: object) -> set[str]:
    """Return the names of arguments marked ``required=True``."""
    args = getattr(definition, "arguments", None) or []
    return {a.name for a in args if a.required}


def test_all_prompts_lists_four_definitions() -> None:
    """The package registry exposes the four documented prompts."""
    names = {p.name for p in all_prompts()}
    assert names == {
        "sprint-review",
        "backlog-grooming",
        "triage-bugs",
        "standup-summary",
    }


async def test_sprint_review_definition_and_render() -> None:
    """``/sprint-review`` requires board_id and renders a non-empty body."""
    assert sprint_review.DEFINITION.name == "sprint-review"
    assert _required_args(sprint_review.DEFINITION) == {"board_id"}
    result = await sprint_review.render({"board_id": "7"})
    assert result.messages
    assert result.messages[0].role == "user"
    text = result.messages[0].content.text
    assert "board id 7" in text
    assert "active sprint" in text  # default branch


async def test_sprint_review_with_explicit_sprint_id() -> None:
    """When sprint_id is given, the body references it instead of 'active'."""
    result = await sprint_review.render({"board_id": "7", "sprint_id": "42"})
    text = result.messages[0].content.text
    assert "sprint id 42" in text


async def test_sprint_review_missing_board_id_raises() -> None:
    """Omitting the required board_id is a ValueError."""
    with pytest.raises(ValueError, match="board_id"):
        await sprint_review.render({})


async def test_backlog_grooming_definition_and_render() -> None:
    """``/backlog-grooming`` requires project_key and emits a non-empty body."""
    assert backlog_grooming.DEFINITION.name == "backlog-grooming"
    assert _required_args(backlog_grooming.DEFINITION) == {"project_key"}
    result = await backlog_grooming.render({"project_key": "PROJ"})
    text = result.messages[0].content.text
    assert "PROJ" in text
    assert "30" in text  # 30-day staleness window
    assert "ask" in text.lower()  # confirmation gate


async def test_triage_bugs_definition_and_render() -> None:
    """``/triage-bugs`` requires project_key and emits a non-empty body."""
    assert triage_bugs.DEFINITION.name == "triage-bugs"
    assert _required_args(triage_bugs.DEFINITION) == {"project_key"}
    result = await triage_bugs.render({"project_key": "PROJ"})
    text = result.messages[0].content.text
    assert "PROJ" in text
    assert "Bug" in text
    assert "Open" in text


async def test_standup_summary_definition_and_render() -> None:
    """``/standup-summary`` requires project_key and emits a non-empty body."""
    assert standup_summary.DEFINITION.name == "standup-summary"
    assert _required_args(standup_summary.DEFINITION) == {"project_key"}
    result = await standup_summary.render({"project_key": "PROJ"})
    text = result.messages[0].content.text
    assert "PROJ" in text
    assert "assignee" in text.lower()


async def test_render_prompt_dispatch() -> None:
    """The package-level dispatcher routes by name."""
    result = await render_prompt("triage-bugs", {"project_key": "PROJ"})
    assert result.messages
    assert "PROJ" in result.messages[0].content.text


async def test_render_prompt_unknown_name() -> None:
    """An unknown prompt name surfaces a ValueError."""
    with pytest.raises(ValueError, match="unknown prompt"):
        await render_prompt("does-not-exist", None)
