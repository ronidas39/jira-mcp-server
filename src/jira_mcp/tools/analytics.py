"""Analytics MCP tools.

Jira Cloud has no native aggregation surface for the metrics we want
(per-assignee workload, status histogram, sprint velocity, stale-issue
report), so each of these tools runs one or more JQL searches and
aggregates the result in Python. The pattern is the same in every case:
build a JQL string with the helpers in :mod:`jira_mcp.utils.jql`, page
through the results, and bucket on the relevant field.

Story-point reads use a tenant-configurable custom field. Jira Cloud
defaults to ``customfield_10016`` for the points value; sites that
re-mapped the field can override the constant via a settings extension
when one is added. The constant is module-level so future code can read
it from settings without a refactor.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from mcp import types
from mcp.server import Server
from pydantic import BaseModel

from ..clients.issues import IssueClient
from ..clients.jira import JiraClient
from ..config.settings import Settings
from ..models.jira_entities import Sprint, User
from ..models.tool_io import (
    IssuesByStatusInput,
    IssuesByStatusOutput,
    SprintVelocity,
    StaleIssuesInput,
    StaleIssuesOutput,
    StatusBucket,
    VelocityInput,
    VelocityOutput,
    WorkloadByAssigneeInput,
    WorkloadByAssigneeOutput,
    WorkloadEntry,
)
from ..utils.jql import Jql, project_eq, status_in, updated_before

# Default Jira Cloud field id for "Story points." Tenants that remapped
# the field can plug an override here once settings carries one.
DEFAULT_STORY_POINTS_FIELD = "customfield_10016"

# Default page size for analytic searches. Aggregation runs over up to a
# few thousand issues; 100 is the v3 search hard cap.
_PAGE_SIZE = 100

# Stale-issue defaults: in-progress statuses, since stale Done issues are
# not actionable on any of the workflows we have observed.
_DEFAULT_STALE_STATUSES = ("In Progress", "To Do")

# Floor used when sorting sprints that lack any of the three date fields;
# defined once so the lambda below stays a one-liner.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(slots=True)
class AnalyticsToolContext:
    """Bundle of dependencies the analytics tools need."""

    issues: IssueClient
    jira: JiraClient
    settings: Settings


def _resolve_story_points_field(settings: Settings) -> str:
    """Return the configured story-points field id, falling back to the default.

    Settings does not currently expose a story-points override; the helper
    is the single hook for adding one without rewriting every analytic.
    """
    return getattr(settings, "story_points_field", DEFAULT_STORY_POINTS_FIELD)


async def _search_all(issues: IssueClient, jql: str, fields: list[str]) -> list[dict[str, Any]]:
    """Page through a JQL search and return the raw issue dicts.

    Aggregation needs the raw ``fields`` map so the caller can read custom
    fields by id; the ``IssueSummary`` projection on
    :class:`SearchIssuesOutput` strips those, so this helper falls back to
    the underlying HTTP client for the wire payload.

    Atlassian retired ``/rest/api/3/search`` in 2025; the replacement
    ``/rest/api/3/search/jql`` is cursor-paged via ``nextPageToken`` plus
    ``isLast``, with no ``total`` field, so the loop walks the cursor
    until the server flags the last page.
    """
    out: list[dict[str, Any]] = []
    next_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "jql": jql,
            "maxResults": _PAGE_SIZE,
            "fields": ",".join(fields),
        }
        if next_token:
            params["nextPageToken"] = next_token
        body = await issues._jira.get("/rest/api/3/search/jql", params=params)
        page = body.get("issues") or []
        out.extend(page)
        if body.get("isLast", True):
            break
        next_token = body.get("nextPageToken")
        if not next_token:
            break
    return out


async def workload_by_assignee(
    ctx: AnalyticsToolContext, payload: WorkloadByAssigneeInput
) -> WorkloadByAssigneeOutput:
    """Count open issues and sum story points per assignee.

    Builds a JQL of ``project = X`` plus an optional ``status in (...)``
    filter, pages through the results, and groups by ``assignee.accountId``
    with ``None`` representing the unassigned bucket. Story points are
    summed when present; missing values are treated as zero.
    """
    builder = Jql().where(project_eq(payload.project_key))
    if payload.statuses:
        builder.where(status_in(payload.statuses))
    points_field = _resolve_story_points_field(ctx.settings)
    raw_issues = await _search_all(
        ctx.issues, builder.build(), fields=["assignee", points_field, "summary"]
    )

    counts: Counter[str | None] = Counter()
    points: dict[str | None, float] = {}
    user_lookup: dict[str | None, dict[str, Any] | None] = {}
    for issue in raw_issues:
        fields = issue.get("fields") or {}
        assignee = fields.get("assignee")
        bucket: str | None = assignee.get("accountId") if isinstance(assignee, dict) else None
        counts[bucket] += 1
        user_lookup.setdefault(bucket, assignee if isinstance(assignee, dict) else None)
        sp = fields.get(points_field)
        if isinstance(sp, int | float):
            points[bucket] = points.get(bucket, 0.0) + float(sp)

    entries: list[WorkloadEntry] = []
    for bucket, count in counts.most_common():
        user_payload = user_lookup.get(bucket)
        user = User.model_validate(user_payload) if user_payload else None
        entries.append(WorkloadEntry(assignee=user, open_issues=count))
    return WorkloadByAssigneeOutput(entries=entries)


async def issues_by_status(
    ctx: AnalyticsToolContext, payload: IssuesByStatusInput
) -> IssuesByStatusOutput:
    """Count issues per status name within a project."""
    builder = Jql().where(project_eq(payload.project_key))
    raw_issues = await _search_all(ctx.issues, builder.build(), fields=["status", "summary"])
    counts: Counter[str] = Counter()
    for issue in raw_issues:
        fields = issue.get("fields") or {}
        status = fields.get("status") or {}
        name = status.get("name") if isinstance(status, dict) else None
        if name:
            counts[name] += 1
    buckets = [StatusBucket(status=name, count=count) for name, count in counts.most_common()]
    return IssuesByStatusOutput(buckets=buckets)


async def velocity(ctx: AnalyticsToolContext, payload: VelocityInput) -> VelocityOutput:
    """Compute completed and committed story points per closed sprint.

    Uses ``GET /rest/agile/1.0/board/{id}/sprint?state=closed`` to list the
    most recently closed sprints. For each, ``committed`` is the sum of
    points for issues that were in the sprint at start, and ``completed``
    is the sum for issues that ended in a Done status category at sprint
    end. The agile API does not separate these natively, so we approximate
    using the JQL functions ``sprint = N`` and the issue's resolution date.
    """
    points_field = _resolve_story_points_field(ctx.settings)
    sprints_resp = await ctx.jira.get(
        f"/rest/agile/1.0/board/{payload.board_id}/sprint",
        params={"state": "closed"},
    )
    raw_sprints = sprints_resp.get("values") or []
    sprints = [Sprint.model_validate(s) for s in raw_sprints]
    # Most recent first, then trim to the requested count, then flip back
    # to ascending so the report reads left-to-right oldest to newest. The
    # ``_EPOCH`` fallback ensures sprints with no recorded dates sort to the
    # bottom rather than crashing the comparator on a ``None`` value.
    sprints.sort(
        key=lambda s: s.complete_date or s.end_date or s.start_date or _EPOCH,
        reverse=True,
    )
    selected = list(reversed(sprints[: payload.sprint_count]))

    per_sprint: list[SprintVelocity] = []
    for sprint in selected:
        committed = await _sum_points(ctx, sprint.id, points_field, only_done=False)
        completed = await _sum_points(ctx, sprint.id, points_field, only_done=True)
        per_sprint.append(
            SprintVelocity(
                sprint=sprint,
                completed_points=completed,
                committed_points=committed,
            )
        )
    avg = sum(s.completed_points for s in per_sprint) / len(per_sprint) if per_sprint else 0.0
    return VelocityOutput(sprints=per_sprint, average_completed=avg)


async def _sum_points(
    ctx: AnalyticsToolContext, sprint_id: int, points_field: str, *, only_done: bool
) -> float:
    """Sum the story-points field across the issues in one sprint.

    ``only_done`` toggles the Done filter for the "completed" leg of the
    velocity calculation.
    """
    builder = Jql().where(f"sprint = {sprint_id}")
    if only_done:
        builder.where("statusCategory = Done")
    raw_issues = await _search_all(ctx.issues, builder.build(), fields=[points_field])
    total = 0.0
    for issue in raw_issues:
        fields = issue.get("fields") or {}
        sp = fields.get(points_field)
        if isinstance(sp, int | float):
            total += float(sp)
    return total


async def stale_issues(ctx: AnalyticsToolContext, payload: StaleIssuesInput) -> StaleIssuesOutput:
    """Return open issues that have not been updated in N days, oldest first."""
    statuses = payload.statuses or list(_DEFAULT_STALE_STATUSES)
    builder = (
        Jql()
        .where(project_eq(payload.project_key))
        .where(status_in(statuses))
        .where(updated_before(payload.days))
        .order_by("updated ASC")
    )
    out = await ctx.issues.search(jql=builder.build(), max_results=_PAGE_SIZE)
    return StaleIssuesOutput(issues=out.issues)


_TOOL_DESCRIPTIONS: dict[str, str] = {
    "workload_by_assignee": (
        "Count open issues and sum story points per assignee in a project. "
        "Use this for capacity reviews. Status filter defaults to all "
        "non-Done statuses when omitted."
    ),
    "issues_by_status": (
        "Histogram of issues by status name in one project. Use this "
        "before workload reports if the caller is unsure which statuses "
        "matter."
    ),
    "velocity": (
        "Average completed story points across the last N closed sprints "
        "of a scrum board. Use this for forecasting; do not interpret a "
        "single sprint as a trend."
    ),
    "stale_issues": (
        "Open issues with no update in N days, sorted oldest first. Use "
        "this to surface neglected work; defaults to a 14-day window and "
        "in-progress statuses."
    ),
}


_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "workload_by_assignee": WorkloadByAssigneeInput,
    "issues_by_status": IssuesByStatusInput,
    "velocity": VelocityInput,
    "stale_issues": StaleIssuesInput,
}


_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "workload_by_assignee": WorkloadByAssigneeOutput,
    "issues_by_status": IssuesByStatusOutput,
    "velocity": VelocityOutput,
    "stale_issues": StaleIssuesOutput,
}


def _build_tool_definitions() -> list[types.Tool]:
    """Construct the SDK Tool objects for the analytics tools."""
    out: list[types.Tool] = []
    for name, description in _TOOL_DESCRIPTIONS.items():
        out.append(
            types.Tool(
                name=name,
                description=description,
                inputSchema=_INPUT_MODELS[name].model_json_schema(),
                outputSchema=_OUTPUT_MODELS[name].model_json_schema(),
            )
        )
    return out


async def _dispatch(
    ctx: AnalyticsToolContext, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Route an analytics tool call to its handler."""
    if name == "workload_by_assignee":
        out_w = await workload_by_assignee(ctx, WorkloadByAssigneeInput.model_validate(arguments))
        return out_w.model_dump(mode="json", by_alias=True)
    if name == "issues_by_status":
        out_s = await issues_by_status(ctx, IssuesByStatusInput.model_validate(arguments))
        return out_s.model_dump(mode="json", by_alias=True)
    if name == "velocity":
        out_v = await velocity(ctx, VelocityInput.model_validate(arguments))
        return out_v.model_dump(mode="json", by_alias=True)
    if name == "stale_issues":
        out_st = await stale_issues(ctx, StaleIssuesInput.model_validate(arguments))
        return out_st.model_dump(mode="json", by_alias=True)
    raise ValueError(f"unknown analytics tool: {name}")


ToolEntry = tuple[types.Tool, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]


def register(server: Server, ctx: AnalyticsToolContext) -> dict[str, ToolEntry]:
    """Build and return the analytics tool registry the bootstrap installs.

    The MCP SDK only supports a single ``list_tools`` and ``call_tool``
    handler per server, so we hand back a registry instead of installing
    decorators directly. The bootstrap merges every group's registry
    before wiring the global handlers.

    Args:
        server: The MCP server instance, kept for parity.
        ctx: Bound dependencies (issue client, jira client, settings).

    Returns:
        Map from tool name to ``(Tool, handler)``.
    """
    del server
    tool_defs = {t.name: t for t in _build_tool_definitions()}
    registry: dict[str, ToolEntry] = {}
    for name, tool in tool_defs.items():

        async def _handler(args: dict[str, Any], *, _name: str = name) -> dict[str, Any]:
            return await _dispatch(ctx, _name, args)

        registry[name] = (tool, _handler)
    return registry


__all__ = ["AnalyticsToolContext", "ToolEntry", "register"]
