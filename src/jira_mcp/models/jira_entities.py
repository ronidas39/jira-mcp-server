"""Pydantic models that mirror Jira Cloud REST API v3 response shapes.

Jira's wire format is wide, polymorphic, and changes from one tenant to the
next (custom fields, expansion params, deprecated key aliases). The strategy
here is defensive: every model uses ``extra="ignore"`` so unknown fields do
not blow up parsing, and ``populate_by_name=True`` so we can present clean
snake_case names to Python while still accepting Jira's camelCase keys via
``Field(alias=...)``.

Only the fields that downstream tools actually consume are typed. Anything
else is captured into a generic ``fields`` dict on ``Issue`` so callers that
need custom fields can reach them by id (e.g. ``cf[10005]``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Shared model configuration. Centralized so a future change (e.g. flipping
# extra to "allow" for debugging) is a one-line edit instead of a sweep.
_MODEL_CONFIG = ConfigDict(populate_by_name=True, extra="ignore")


class User(BaseModel):
    """A Jira account.

    Jira identifies users by ``accountId`` in Cloud; ``key`` and ``name`` were
    deprecated when GDPR-mode became default. We keep ``email_address`` and
    ``display_name`` because almost every workload report needs a human label
    and the email is what users actually type when assigning issues.
    """

    model_config = _MODEL_CONFIG

    account_id: str = Field(alias="accountId")
    display_name: str | None = Field(default=None, alias="displayName")
    email_address: str | None = Field(default=None, alias="emailAddress")
    active: bool = True
    account_type: str | None = Field(default=None, alias="accountType")
    time_zone: str | None = Field(default=None, alias="timeZone")


class Project(BaseModel):
    """A Jira project.

    ``key`` is the user-visible identifier ("PROJ"). ``id`` is the numeric
    primary key Jira uses internally; both are returned on most endpoints so
    we keep both to avoid an extra lookup later.
    """

    model_config = _MODEL_CONFIG

    id: str
    key: str
    name: str
    project_type_key: str | None = Field(default=None, alias="projectTypeKey")
    lead: User | None = None
    description: str | None = None


class IssueType(BaseModel):
    """Issue type metadata (Bug, Story, Epic, ...).

    ``subtask`` is exposed because reporting tools often want to exclude
    subtasks from rollups, and the only authoritative signal lives here.
    """

    model_config = _MODEL_CONFIG

    id: str
    name: str
    subtask: bool = False
    description: str | None = None
    icon_url: str | None = Field(default=None, alias="iconUrl")


class StatusCategory(BaseModel):
    """Coarse status grouping ("To Do", "In Progress", "Done").

    Jira nests this under ``status.statusCategory``; it is the only stable
    way to group user-defined workflow statuses across projects.
    """

    model_config = _MODEL_CONFIG

    id: int
    key: str
    name: str
    color_name: str | None = Field(default=None, alias="colorName")


class Status(BaseModel):
    """Workflow status of an issue."""

    model_config = _MODEL_CONFIG

    id: str
    name: str
    description: str | None = None
    status_category: StatusCategory | None = Field(default=None, alias="statusCategory")


class Priority(BaseModel):
    """Issue priority (e.g. Highest, High, Medium, Low, Lowest)."""

    model_config = _MODEL_CONFIG

    id: str
    name: str
    icon_url: str | None = Field(default=None, alias="iconUrl")


class Comment(BaseModel):
    """A comment on an issue.

    ``body`` is intentionally typed ``Any``: Jira returns ADF (Atlassian
    Document Format) JSON when the issue uses the new editor, and a plain
    string when ``expand=renderedFields`` is requested. Forcing one shape
    here would silently drop content from the other path.
    """

    model_config = _MODEL_CONFIG

    id: str
    author: User | None = None
    body: Any = None
    created: datetime | None = None
    updated: datetime | None = None


class Transition(BaseModel):
    """An available workflow transition.

    Returned by ``GET /rest/api/3/issue/{key}/transitions``. ``to`` carries
    the destination status so the model can present the user-visible name
    rather than a raw transition id.
    """

    model_config = _MODEL_CONFIG

    id: str
    name: str
    to: Status | None = None
    has_screen: bool | None = Field(default=None, alias="hasScreen")
    is_global: bool | None = Field(default=None, alias="isGlobal")
    is_initial: bool | None = Field(default=None, alias="isInitial")


class IssueSummary(BaseModel):
    """Lightweight issue projection used in list responses.

    Search endpoints can return thousands of issues; pulling the full nested
    representation for each one wastes bandwidth and tokens. This summary
    keeps only what a typical list view renders.
    """

    model_config = _MODEL_CONFIG

    id: str
    key: str
    summary: str
    status: Status | None = None
    assignee: User | None = None
    priority: Priority | None = None
    issue_type: IssueType | None = Field(default=None, alias="issuetype")
    updated: datetime | None = None


class Issue(BaseModel):
    """A full Jira issue.

    Jira's REST shape is ``{id, key, fields: {...}}`` with most attributes
    nested under ``fields``. We flatten the most-used fields onto the top
    level for ergonomic access while still preserving the full ``fields``
    dict so custom fields stay reachable.

    The flattening uses a model validator (in ``_flatten_fields``) so callers
    can pass the raw Jira payload directly without preprocessing.
    """

    model_config = _MODEL_CONFIG

    id: str
    key: str
    self_url: str | None = Field(default=None, alias="self")

    summary: str = ""
    description: Any = None
    status: Status | None = None
    assignee: User | None = None
    reporter: User | None = None
    priority: Priority | None = None
    issue_type: IssueType | None = Field(default=None, alias="issuetype")
    project: Project | None = None
    labels: list[str] = Field(default_factory=list)
    created: datetime | None = None
    updated: datetime | None = None
    due_date: datetime | None = Field(default=None, alias="duedate")
    resolution_date: datetime | None = Field(default=None, alias="resolutiondate")

    comments: list[Comment] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)

    fields: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Issue:
        """Build an ``Issue`` from a raw Jira API payload.

        The Jira shape nests almost everything inside ``fields``. Doing the
        flattening here (rather than in a validator) keeps the model usable
        in two modes: pre-flattened (tests, fixtures) and raw-from-Jira
        (live calls). A validator would force every caller to match one
        shape exactly.
        """
        fields = payload.get("fields") or {}
        comments_block = fields.get("comment") or {}
        comments_raw = (
            comments_block.get("comments") if isinstance(comments_block, dict) else comments_block
        ) or []
        merged: dict[str, Any] = {
            "id": payload.get("id"),
            "key": payload.get("key"),
            "self": payload.get("self"),
            "summary": fields.get("summary", ""),
            "description": fields.get("description"),
            "status": fields.get("status"),
            "assignee": fields.get("assignee"),
            "reporter": fields.get("reporter"),
            "priority": fields.get("priority"),
            "issuetype": fields.get("issuetype"),
            "project": fields.get("project"),
            "labels": fields.get("labels") or [],
            "created": fields.get("created"),
            "updated": fields.get("updated"),
            "duedate": fields.get("duedate"),
            "resolutiondate": fields.get("resolutiondate"),
            "comments": comments_raw,
            "transitions": payload.get("transitions") or [],
            "fields": fields,
        }
        return cls.model_validate(merged)


class Sprint(BaseModel):
    """An Agile sprint.

    Sprint endpoints live under ``/rest/agile/1.0`` rather than the core
    REST API. ``state`` is one of ``future``, ``active``, ``closed``; we keep
    it as a string because Jira occasionally introduces new states and a
    strict enum would brick the parser when that happens.
    """

    model_config = _MODEL_CONFIG

    id: int
    name: str
    state: str | None = None
    start_date: datetime | None = Field(default=None, alias="startDate")
    end_date: datetime | None = Field(default=None, alias="endDate")
    complete_date: datetime | None = Field(default=None, alias="completeDate")
    origin_board_id: int | None = Field(default=None, alias="originBoardId")
    goal: str | None = None


class Board(BaseModel):
    """An Agile board (scrum or kanban).

    ``location`` carries the project context when the board is project-scoped;
    boards can also be cross-project, in which case Jira omits it.
    """

    model_config = _MODEL_CONFIG

    id: int
    name: str
    type: str | None = None
    project_key: str | None = Field(default=None, alias="projectKey")
    project_id: int | None = Field(default=None, alias="projectId")


__all__ = [
    "Board",
    "Comment",
    "Issue",
    "IssueSummary",
    "IssueType",
    "Priority",
    "Project",
    "Sprint",
    "Status",
    "StatusCategory",
    "Transition",
    "User",
]
