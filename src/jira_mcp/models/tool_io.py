"""Pydantic input and output schemas for MCP tools.

Why every tool gets a model pair:

* The MCP SDK derives the JSON schema it sends to the model from these
  classes, so a clear ``description=`` on every field is what teaches Claude
  when and how to call the tool. Skipping descriptions silently degrades
  tool selection quality.
* Outputs are typed too (rather than ``dict``) so the dispatcher can run
  ``model_dump(mode="json")`` and get stable, well-shaped responses without
  the tool author having to think about serialization.

Models are grouped by capability area and sorted in roughly the order a new
reader would encounter them: read tools first, then write tools, then
analytics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .jira_entities import (
    Board,
    Issue,
    IssueSummary,
    Project,
    Sprint,
    Transition,
    User,
)

_IO_CONFIG = ConfigDict(populate_by_name=True, extra="forbid")


class _IOModel(BaseModel):
    """Base for tool I/O models.

    ``extra="forbid"`` on inputs catches typos in tool calls early; on
    outputs it forces tool authors to declare every field they return,
    which keeps the public contract honest.
    """

    model_config = _IO_CONFIG


# ---------------------------------------------------------------------------
# Search / read
# ---------------------------------------------------------------------------


class SearchIssuesInput(_IOModel):
    """Inputs for a JQL-driven search."""

    jql: str = Field(
        description=(
            "Raw JQL expression. Use this when the caller knows exactly what "
            "they want; for natural-language queries, build JQL with the "
            "helpers in jql.py rather than asking the model to write it."
        ),
    )
    fields: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of issue fields to return. Omit to use Jira's "
            "default navigable field set; pass a narrow list to reduce "
            "payload size on large result sets."
        ),
    )
    start_at: int = Field(
        default=0,
        ge=0,
        description="Zero-based offset into the result set for pagination.",
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=100,
        description=(
            "Maximum issues per page. Jira hard-caps this at 100 for v3 "
            "search; values above that are silently clamped server-side."
        ),
    )


class SearchIssuesOutput(_IOModel):
    """A page of search results."""

    issues: list[IssueSummary] = Field(
        description="Matching issues, projected to the summary shape."
    )
    total: int = Field(description="Total matching issues across all pages, per Jira.")
    start_at: int = Field(description="Offset of the first issue in this page.")
    max_results: int = Field(description="Page size that was actually applied.")


class GetIssueInput(_IOModel):
    """Inputs for fetching a single issue."""

    key: str = Field(description="Issue key, for example PROJ-123. Case-insensitive in Jira.")
    expand_comments: bool = Field(
        default=False,
        description=(
            "If true, include the comments array. Adds a request hop and "
            "increases payload size; only set when the caller actually needs "
            "comment text."
        ),
    )
    expand_transitions: bool = Field(
        default=False,
        description=(
            "If true, include the available workflow transitions. Use this "
            "before calling transition_issue so the caller knows the valid "
            "transition ids."
        ),
    )


class GetIssueOutput(_IOModel):
    """Full issue payload."""

    issue: Issue = Field(description="Full Jira issue with flattened fields.")


class ListProjectsOutput(_IOModel):
    """All projects visible to the authenticated user."""

    projects: list[Project] = Field(
        description="Projects the calling principal can browse, unsorted."
    )


class GetProjectInput(_IOModel):
    """Inputs for fetching a single project."""

    key_or_id: str = Field(description="Project key (e.g. PROJ) or numeric id; both are accepted.")


class GetProjectOutput(_IOModel):
    """Single project payload."""

    project: Project = Field(description="Project details including lead user.")


class ListUsersInput(_IOModel):
    """Inputs for the user picker endpoint."""

    query: str | None = Field(
        default=None,
        description=(
            "Substring to match against display name or email. Omit to list "
            "all users; results are still capped by max_results."
        ),
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Hard upper bound on returned users.",
    )


class ListUsersOutput(_IOModel):
    """Page of user records."""

    users: list[User] = Field(description="Matching users, no ordering guarantee.")


class ResolveUserInput(_IOModel):
    """Inputs for translating a human label to a Jira accountId."""

    identifier: str = Field(
        description=(
            "Email, display name, or accountId. The resolver tries each "
            "lookup in order so callers do not need to know which form they "
            "have."
        ),
    )


class ResolveUserOutput(_IOModel):
    """Resolution result; ``user`` is None when nothing matched."""

    user: User | None = Field(
        default=None,
        description="Resolved user, or null when no unambiguous match exists.",
    )


class ListTransitionsInput(_IOModel):
    """Inputs for fetching workflow transitions for an issue."""

    key: str = Field(description="Issue key whose transitions are requested.")


class ListTransitionsOutput(_IOModel):
    """Available workflow transitions for the given issue."""

    transitions: list[Transition] = Field(
        description="Transitions the caller is permitted to execute right now."
    )


class CustomFieldDescriptor(_IOModel):
    """Metadata for a single Jira custom field."""

    id: str = Field(description="Field id, e.g. customfield_10005.")
    name: str = Field(description="Human-readable field name.")
    custom: bool = Field(description="True for tenant-defined custom fields.")
    schema_type: str | None = Field(
        default=None,
        description="Field schema type as reported by Jira, when available.",
    )


class ListCustomFieldsOutput(_IOModel):
    """All custom fields defined on the Jira tenant."""

    fields: list[CustomFieldDescriptor] = Field(
        description="Custom fields plus selected system fields."
    )


class ListBoardsInput(_IOModel):
    """Inputs for listing Agile boards."""

    project_key: str | None = Field(
        default=None,
        description="Optional project key to filter boards. Omit for all boards.",
    )
    type: str | None = Field(
        default=None,
        description="Board type filter: 'scrum' or 'kanban'.",
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Page size; Agile API caps at 50 by default.",
    )


class ListBoardsOutput(_IOModel):
    """Boards page."""

    boards: list[Board] = Field(description="Matching boards.")


class ListSprintsInput(_IOModel):
    """Inputs for listing sprints on a board."""

    board_id: int = Field(description="Agile board id whose sprints to list.")
    state: str | None = Field(
        default=None,
        description=(
            "Optional sprint state filter: 'future', 'active', or 'closed'. "
            "Comma-separated values are accepted by Jira."
        ),
    )


class ListSprintsOutput(_IOModel):
    """Sprints page."""

    sprints: list[Sprint] = Field(description="Sprints matching the filter.")


class GetSprintInput(_IOModel):
    """Inputs for fetching a single sprint by id."""

    sprint_id: int = Field(description="Numeric sprint id.")


class GetSprintOutput(_IOModel):
    """Single-sprint payload."""

    sprint: Sprint = Field(description="Sprint details including dates and goal.")


class MoveToSprintInput(_IOModel):
    """Inputs for moving issues into a sprint."""

    sprint_id: int = Field(description="Target sprint id; the agile API accepts numeric ids only.")
    issue_keys: list[str] = Field(
        min_length=1,
        description=(
            "Issue keys to move into the sprint, e.g. ['PROJ-1', 'PROJ-2']. "
            "Jira's agile endpoint hard-caps at 50 keys per request; the "
            "client batches longer lists internally."
        ),
    )


class MoveToSprintOutput(_IOModel):
    """Result of a sprint-move operation."""

    moved_count: int = Field(description="Total number of issues Jira accepted across all batches.")


class SprintReportInput(_IOModel):
    """Inputs for the sprint synthesis report."""

    sprint_id: int = Field(
        description="Sprint id to summarise; uses the active sprint state at fetch time."
    )


class SprintReportOutput(_IOModel):
    """Synthesised sprint report.

    The committed count is approximated from the issues currently associated
    with the sprint because the precise "scope at sprint start" requires a
    changelog scan that is too heavy for an interactive tool. ``at_risk`` is
    populated only while the sprint is still in the ``active`` state and the
    end date has passed; closed sprints report zero at_risk by convention.
    """

    sprint: Sprint = Field(description="Sprint metadata used for the report.")
    committed: int = Field(
        description=(
            "Approximate count of issues committed at sprint start. Derived "
            "from the current sprint membership; see class docstring for the "
            "trade off."
        ),
    )
    delivered: int = Field(
        description=("Issues whose status category is 'done' at the time of fetch."),
    )
    at_risk: int = Field(
        description=(
            "Issues still in progress past the sprint end date while the "
            "sprint is active. Always 0 for closed or future sprints."
        ),
    )
    issues: list[IssueSummary] = Field(
        description="The full set of issues currently linked to the sprint."
    )


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


class WorkloadByAssigneeInput(_IOModel):
    """Inputs for the workload-per-assignee report."""

    project_key: str = Field(description="Project to scope the report to.")
    statuses: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of status names to include. Defaults to all "
            "non-Done statuses, which is what most workload questions mean."
        ),
    )


class WorkloadEntry(_IOModel):
    """One row of a workload report."""

    assignee: User | None = Field(
        default=None,
        description="Assignee, or null for the 'Unassigned' bucket.",
    )
    open_issues: int = Field(description="Count of issues currently assigned.")


class WorkloadByAssigneeOutput(_IOModel):
    """Workload report."""

    entries: list[WorkloadEntry] = Field(
        description="One entry per assignee, sorted descending by open_issues."
    )


class IssuesByStatusInput(_IOModel):
    """Inputs for an issues-by-status grouping."""

    project_key: str = Field(description="Project to scope the grouping to.")


class StatusBucket(_IOModel):
    """Count of issues in a single status."""

    status: str = Field(description="Status name as it appears in the workflow.")
    count: int = Field(description="Number of issues currently in this status.")


class IssuesByStatusOutput(_IOModel):
    """Status histogram."""

    buckets: list[StatusBucket] = Field(
        description="One bucket per status, including statuses with zero issues."
    )


class VelocityInput(_IOModel):
    """Inputs for sprint velocity calculation."""

    board_id: int = Field(description="Scrum board to compute velocity for.")
    sprint_count: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "Number of most recently completed sprints to average. Five is a "
            "common default in agile planning literature."
        ),
    )


class SprintVelocity(_IOModel):
    """Velocity for a single sprint."""

    sprint: Sprint = Field(description="The sprint being measured.")
    completed_points: float = Field(description="Story points completed in this sprint.")
    committed_points: float = Field(description="Story points committed at sprint start.")


class VelocityOutput(_IOModel):
    """Velocity report."""

    sprints: list[SprintVelocity] = Field(
        description="Per-sprint breakdown, ordered oldest to newest."
    )
    average_completed: float = Field(
        description="Mean completed points across the analyzed sprints."
    )


class StaleIssuesInput(_IOModel):
    """Inputs for the stale-issues report."""

    project_key: str = Field(description="Project to scope the search.")
    days: int = Field(
        default=14,
        ge=1,
        le=365,
        description=(
            "Issues with no update in this many days are considered stale. "
            "14 mirrors a typical sprint length."
        ),
    )
    statuses: list[str] | None = Field(
        default=None,
        description=(
            "Optional status filter. Defaults to in-progress statuses since "
            "stale Done issues are rarely actionable."
        ),
    )


class StaleIssuesOutput(_IOModel):
    """Stale issues report."""

    issues: list[IssueSummary] = Field(
        description="Matching issues, sorted ascending by last update."
    )


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


class CreateIssueInput(_IOModel):
    """Inputs for creating a single issue."""

    project_key: str = Field(description="Project that will own the new issue.")
    summary: str = Field(
        min_length=1,
        description="One-line title shown in lists and the issue header.",
    )
    issue_type: str = Field(description="Issue type name, e.g. 'Bug', 'Story', 'Task'.")
    description: str | None = Field(
        default=None,
        description=(
            "Optional plain-text description. The server converts it to ADF "
            "before sending so callers do not have to build the document tree."
        ),
    )
    assignee_account_id: str | None = Field(
        default=None,
        description="Optional Jira accountId. Resolve emails first via resolve_user.",
    )
    priority: str | None = Field(
        default=None,
        description="Optional priority name (e.g. 'High'). Tenant-defined.",
    )
    labels: list[str] | None = Field(
        default=None,
        description="Optional labels to attach at creation time.",
    )
    custom_fields: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional map of custom field id to value, e.g. "
            "{'customfield_10005': 'EPIC-1'}. Pass values pre-shaped for "
            "Jira; the server does not infer field types."
        ),
    )


class CreateIssueOutput(_IOModel):
    """Result of an issue create."""

    key: str = Field(description="Issue key Jira assigned, e.g. PROJ-123.")
    id: str = Field(description="Numeric issue id.")
    self_url: str = Field(description="Canonical REST URL for the new issue.")


class UpdateIssueInput(_IOModel):
    """Inputs for partial issue updates."""

    key: str = Field(description="Issue key to update.")
    summary: str | None = Field(
        default=None,
        description="New summary; omit to leave unchanged.",
    )
    description: str | None = Field(
        default=None,
        description="New plain-text description; converted to ADF server-side.",
    )
    assignee_account_id: str | None = Field(
        default=None,
        description=(
            "New assignee accountId. Pass an empty string to unassign; null "
            "leaves the field untouched."
        ),
    )
    priority: str | None = Field(
        default=None,
        description="New priority name; omit to leave unchanged.",
    )
    labels: list[str] | None = Field(
        default=None,
        description="Replacement label set; omit to leave labels untouched.",
    )
    custom_fields: dict[str, Any] | None = Field(
        default=None,
        description="Custom field id to value map for partial update.",
    )


class UpdateIssueOutput(_IOModel):
    """Result of an issue update."""

    key: str = Field(description="Issue key that was updated.")
    updated: bool = Field(description="True when Jira accepted the update; false on no-op.")


class TransitionIssueInput(_IOModel):
    """Inputs for moving an issue through its workflow."""

    key: str = Field(description="Issue key to transition.")
    transition_id: str = Field(
        description=(
            "Numeric transition id from list_transitions. Names are not "
            "globally unique across workflows, so id is required."
        ),
    )
    comment: str | None = Field(
        default=None,
        description="Optional comment to attach when the transition completes.",
    )


class TransitionIssueOutput(_IOModel):
    """Result of a transition."""

    key: str = Field(description="Issue key that was transitioned.")
    new_status: str | None = Field(
        default=None,
        description="Status the issue ended up in, when reported by Jira.",
    )


class BulkCreateIssueItem(_IOModel):
    """One issue in a bulk-create request.

    Mirrors ``CreateIssueInput`` but allows partial validation so a single
    bad row does not fail the whole batch.
    """

    project_key: str = Field(description="Project key for this row.")
    summary: str = Field(min_length=1, description="Issue summary for this row.")
    issue_type: str = Field(description="Issue type name for this row.")
    description: str | None = Field(default=None, description="Optional description.")
    assignee_account_id: str | None = Field(
        default=None, description="Optional assignee accountId."
    )
    priority: str | None = Field(default=None, description="Optional priority name.")
    labels: list[str] | None = Field(default=None, description="Optional labels.")
    custom_fields: dict[str, Any] | None = Field(
        default=None, description="Optional custom field map."
    )


class BulkCreateIssuesInput(_IOModel):
    """Inputs for bulk issue creation."""

    issues: list[BulkCreateIssueItem] = Field(
        min_length=1,
        max_length=50,
        description=(
            "Issues to create in one batch. Capped at 50 to stay well below "
            "Jira's bulk endpoint limit and to keep failure blast radius small."
        ),
    )


class BulkCreateResultItem(_IOModel):
    """Outcome for a single row in a bulk create."""

    index: int = Field(description="Zero-based index in the input list.")
    key: str | None = Field(default=None, description="Issue key when creation succeeded.")
    error: str | None = Field(
        default=None, description="Human-readable error when creation failed."
    )


class BulkCreateIssuesOutput(_IOModel):
    """Per-row outcomes from a bulk create."""

    results: list[BulkCreateResultItem] = Field(
        description="One entry per input issue, in the same order."
    )


class AddCommentInput(_IOModel):
    """Inputs for adding a comment."""

    key: str = Field(description="Issue key to comment on.")
    body: str = Field(
        min_length=1,
        description=(
            "Plain-text comment body. The server wraps it in an ADF paragraph "
            "before posting so callers can stay in plain text."
        ),
    )


class AddCommentOutput(_IOModel):
    """Result of an add-comment call."""

    id: str = Field(description="Comment id assigned by Jira.")
    created: datetime | None = Field(
        default=None, description="Timestamp Jira recorded for the comment."
    )


class LinkIssuesInput(_IOModel):
    """Inputs for creating an issue link."""

    inward_key: str = Field(
        description=(
            "The 'subject' of the link. For 'A blocks B', A is the inward "
            "key when type is 'Blocks'. Jira's terminology is inverted from "
            "what most users expect, so verify against your link types."
        ),
    )
    outward_key: str = Field(
        description="The 'object' of the link; see inward_key for the convention."
    )
    link_type: str = Field(
        description=(
            "Link type name as configured in Jira, e.g. 'Blocks', 'Relates'. "
            "Type names are tenant-specific."
        ),
    )
    comment: str | None = Field(
        default=None,
        description="Optional comment to record alongside the link creation.",
    )


class LinkIssuesOutput(_IOModel):
    """Result of a link-creation call."""

    linked: bool = Field(description="True when Jira accepted the link.")


__all__ = [
    "AddCommentInput",
    "AddCommentOutput",
    "BulkCreateIssueItem",
    "BulkCreateIssuesInput",
    "BulkCreateIssuesOutput",
    "BulkCreateResultItem",
    "CreateIssueInput",
    "CreateIssueOutput",
    "CustomFieldDescriptor",
    "GetIssueInput",
    "GetIssueOutput",
    "GetProjectInput",
    "GetProjectOutput",
    "GetSprintInput",
    "GetSprintOutput",
    "IssuesByStatusInput",
    "IssuesByStatusOutput",
    "LinkIssuesInput",
    "LinkIssuesOutput",
    "ListBoardsInput",
    "ListBoardsOutput",
    "ListCustomFieldsOutput",
    "ListProjectsOutput",
    "ListSprintsInput",
    "ListSprintsOutput",
    "ListTransitionsInput",
    "ListTransitionsOutput",
    "ListUsersInput",
    "ListUsersOutput",
    "MoveToSprintInput",
    "MoveToSprintOutput",
    "ResolveUserInput",
    "ResolveUserOutput",
    "SearchIssuesInput",
    "SearchIssuesOutput",
    "SprintReportInput",
    "SprintReportOutput",
    "SprintVelocity",
    "StaleIssuesInput",
    "StaleIssuesOutput",
    "StatusBucket",
    "TransitionIssueInput",
    "TransitionIssueOutput",
    "UpdateIssueInput",
    "UpdateIssueOutput",
    "VelocityInput",
    "VelocityOutput",
    "WorkloadByAssigneeInput",
    "WorkloadByAssigneeOutput",
    "WorkloadEntry",
]
