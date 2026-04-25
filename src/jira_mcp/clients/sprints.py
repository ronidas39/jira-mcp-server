"""Sprint and board domain client wrapping :class:`JiraClient`.

The agile endpoints live under ``/rest/agile/1.0/`` rather than the core
``/rest/api/3/`` namespace. This module owns those routes and translates the
JSON envelopes Jira returns into the typed entities downstream tools consume.

Pagination convention across these endpoints: a response carries ``startAt``,
``maxResults``, ``isLast`` and a ``values`` array. We chase pages by
incrementing ``startAt`` by the number of items returned until ``isLast`` is
true. A defensive iteration cap exists because some tenants ship malformed
``isLast`` flags during board migrations and we do not want a runaway loop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models.jira_entities import Board, IssueSummary, Sprint
from ..models.tool_io import SprintReportOutput
from .jira import JiraClient

# Agile move-to-sprint endpoint hard-caps the request payload at 50 keys.
# Splitting larger lists client-side keeps callers from having to know the
# limit and lets us report a single aggregate count back.
_MOVE_BATCH_SIZE = 50

# Hard ceiling on pagination loops. Jira's largest documented agile result
# set fits well under this; a higher value would only mask a buggy server
# response that fails to set ``isLast``.
_MAX_PAGES = 50

# "Done" is the status-category key Jira returns for completed work across
# every workflow. Pinning the literal here avoids re-deriving it at call sites.
_DONE_CATEGORY_KEY = "done"


def _flatten_board(raw: dict[str, Any]) -> dict[str, Any]:
    """Lift ``location.projectKey`` and ``location.projectId`` to the top level.

    Why a manual flatten: the :class:`Board` model exposes ``project_key``
    flat, but Jira nests the project context inside a ``location`` object.
    Doing the lift in one place keeps the model declarations clean and
    avoids leaking Jira's wire shape into every consumer.
    """
    location = raw.get("location") or {}
    merged: dict[str, Any] = dict(raw)
    if "projectKey" not in merged and isinstance(location, dict):
        if "projectKey" in location:
            merged["projectKey"] = location["projectKey"]
        if "projectId" in location:
            merged["projectId"] = location["projectId"]
    return merged


def _summary_from_issue(raw: dict[str, Any]) -> IssueSummary:
    """Build an :class:`IssueSummary` from a Jira issue envelope.

    The agile sprint-issue endpoint returns the same ``{id, key, fields}``
    shape as the core search endpoint, so the projection mirrors what
    :class:`IssueClient` does to keep the two parsers in lockstep.
    """
    fields = raw.get("fields") or {}
    merged = {"id": raw.get("id"), "key": raw.get("key"), **fields}
    return IssueSummary.model_validate(merged)


class SprintClient:
    """Domain client for Jira agile sprint and board endpoints."""

    def __init__(self, jira: JiraClient) -> None:
        """Bind the underlying HTTP client.

        Args:
            jira: A configured :class:`JiraClient`. Shared with sibling
                domain clients; this class never closes it.
        """
        self._jira = jira

    async def list_boards(self, project_key: str | None = None) -> list[Board]:
        """List agile boards, optionally filtered to one project.

        Args:
            project_key: Optional project key (e.g. ``PROJ``). When provided
                Jira filters server-side via ``projectKeyOrId``.

        Returns:
            Every board visible to the caller across all pages.
        """
        params: dict[str, Any] = {}
        if project_key:
            params["projectKeyOrId"] = project_key
        raw_pages = await self._paginate("/rest/agile/1.0/board", params)
        return [Board.model_validate(_flatten_board(item)) for item in raw_pages]

    async def list_sprints(self, board_id: int, state: str | None = None) -> list[Sprint]:
        """List sprints on a board, optionally filtered by state.

        Args:
            board_id: Numeric agile board id.
            state: Optional comma-separated state filter (``future``,
                ``active``, ``closed``).

        Returns:
            Every sprint on the board that matches ``state``.
        """
        params: dict[str, Any] = {}
        if state:
            params["state"] = state
        path = f"/rest/agile/1.0/board/{board_id}/sprint"
        raw_pages = await self._paginate(path, params)
        return [Sprint.model_validate(item) for item in raw_pages]

    async def get_sprint(self, sprint_id: int) -> Sprint:
        """Fetch a single sprint by id."""
        body = await self._jira.get(f"/rest/agile/1.0/sprint/{sprint_id}")
        return Sprint.model_validate(body)

    async def sprint_issues(
        self, sprint_id: int, fields: list[str] | None = None
    ) -> list[IssueSummary]:
        """List issues currently in a sprint.

        Args:
            sprint_id: Sprint to query.
            fields: Optional Jira field list, sent as a comma-separated
                ``fields`` query param. ``None`` defers to Jira's default
                navigable set.
        """
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = ",".join(fields)
        path = f"/rest/agile/1.0/sprint/{sprint_id}/issue"
        body = await self._jira.get(path, params=params)
        raw_issues = body.get("issues") or []
        return [_summary_from_issue(item) for item in raw_issues]

    async def move_to_sprint(self, issue_keys: list[str], sprint_id: int) -> dict[str, int]:
        """Move issues into a sprint, batching at the API's 50-key ceiling.

        Args:
            issue_keys: Issue keys to move. Lists longer than 50 are split
                into successive POSTs.
            sprint_id: Destination sprint id.

        Returns:
            ``{"moved_count": N}`` where ``N`` is the total number of keys
            Jira accepted across all batches.
        """
        moved = 0
        for start in range(0, len(issue_keys), _MOVE_BATCH_SIZE):
            batch = issue_keys[start : start + _MOVE_BATCH_SIZE]
            if not batch:
                continue
            await self._jira.post(
                f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                json={"issues": batch},
            )
            moved += len(batch)
        return {"moved_count": moved}

    async def sprint_report(self, sprint_id: int) -> SprintReportOutput:
        """Synthesise a sprint report from sprint metadata and current issues.

        Computation policy:
            * ``committed`` is approximated as the count of issues currently
              linked to the sprint. The precise definition (scope as of the
              sprint start) requires walking each issue's changelog for
              ``Sprint`` field transitions and is intentionally out of scope
              for this synchronous tool.
            * ``delivered`` counts issues whose status category key equals
              ``done`` at fetch time.
            * ``at_risk`` counts issues that are not done while the sprint is
              both active and past its end date. Closed and future sprints
              report zero by definition.
        """
        sprint = await self.get_sprint(sprint_id)
        issues = await self.sprint_issues(sprint_id)
        delivered = sum(1 for i in issues if _is_done(i))
        at_risk = _count_at_risk(sprint, issues)
        return SprintReportOutput(
            sprint=sprint,
            committed=len(issues),
            delivered=delivered,
            at_risk=at_risk,
            issues=issues,
        )

    async def _paginate(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Walk ``startAt``/``isLast`` pagination and return every value.

        Defensive against malformed responses: a missing ``isLast`` is
        treated as terminal, an empty ``values`` array breaks the loop, and
        a global page cap caps the worst-case iteration count.
        """
        results: list[dict[str, Any]] = []
        start_at = 0
        for _ in range(_MAX_PAGES):
            page_params: dict[str, Any] = {**params, "startAt": start_at}
            body = await self._jira.get(path, params=page_params)
            values = body.get("values") or []
            if not values:
                break
            results.extend(values)
            if body.get("isLast", True):
                break
            start_at += len(values)
        return results


def _is_done(issue: IssueSummary) -> bool:
    """Return True when the issue's status category key is ``done``."""
    status = issue.status
    if status is None or status.status_category is None:
        return False
    return status.status_category.key == _DONE_CATEGORY_KEY


def _count_at_risk(sprint: Sprint, issues: list[IssueSummary]) -> int:
    """Count not-done issues that survived past the sprint end date.

    Only meaningful for active sprints whose end date has elapsed. Future
    sprints have no risk because work has not started; closed sprints have
    already realised their outcome and reporting risk on them would be
    misleading.
    """
    if (sprint.state or "").lower() != "active":
        return 0
    end = sprint.end_date
    if end is None:
        return 0
    now = datetime.now(UTC)
    end_utc = end if end.tzinfo is not None else end.replace(tzinfo=UTC)
    if now <= end_utc:
        return 0
    return sum(1 for i in issues if not _is_done(i))


__all__ = ["SprintClient"]
