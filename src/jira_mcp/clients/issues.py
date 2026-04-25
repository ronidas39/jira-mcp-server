"""Issue-domain client wrapping :class:`JiraClient`.

This module owns the issue-shaped Jira REST endpoints (``/rest/api/3/issue``
and friends). It does two jobs only: shape the request body Jira expects,
and parse the response into the matching Pydantic model. Anything cross
cutting (retries, auth, status-code mapping) lives on ``JiraClient`` and is
inherited by virtue of going through it.

Markdown-to-ADF conversion is intentionally minimal: a full ADF spec
implementation is several hundred lines of node grammar and we do not need
that for v1. Plain text is wrapped in a single paragraph node; bullet lists,
code fences, and the rest pass through verbatim as text content. This is a
conscious v1 trade off, recorded as a design choice so the next milestone
can plug in a real parser without touching call sites.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..models.jira_entities import Issue, Transition
from ..models.tool_io import (
    AddCommentOutput,
    BulkCreateIssueItem,
    BulkCreateIssuesOutput,
    BulkCreateResultItem,
    CreateIssueInput,
    CreateIssueOutput,
    IssueSummary,
    LinkIssuesOutput,
    ListTransitionsOutput,
    SearchIssuesOutput,
    TransitionIssueOutput,
    UpdateIssueOutput,
)
from .jira import JiraClient

# Cap chosen per Jira documentation for the bulk-create endpoint; values above
# are accepted by some tenants and rejected by others, so we clamp client-side.
_BULK_CREATE_CAP = 50

# Per-item creation concurrency for the fallback path. Keeps us within the
# default rate-limit budget while still finishing a 50-issue batch in seconds.
_FALLBACK_CONCURRENCY = 4


def markdown_to_adf(text: str) -> dict[str, Any]:
    """Wrap ``text`` in a minimal ADF document.

    Args:
        text: A plain-text or lightly marked-up string. Bullet lists, code
            fences, and other markdown constructs are not parsed; they pass
            through as the literal characters of a single text node.

    Returns:
        An ADF document dict that Jira accepts on every body field that
        takes ADF (descriptions, comments, transition comments).

    Why minimal: ADF is a tree grammar with dozens of node types; building a
    correct parser is out of scope for v1. The single-paragraph form is
    sufficient for the create, update, comment, and transition flows the
    tools layer exposes. Callers needing rich formatting should pass an ADF
    dict directly through ``custom_fields`` once that path exists.
    """
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _summary_field_set(fields: list[str] | None) -> str | None:
    """Translate the optional fields list to the Jira ``fields`` query param."""
    if fields is None:
        return None
    return ",".join(fields)


def _build_create_fields(payload: CreateIssueInput | BulkCreateIssueItem) -> dict[str, Any]:
    """Map a create-input model into Jira's nested ``fields`` envelope.

    Both single-create and bulk-create rows share the same shape, so the
    builder accepts either model. Optional attributes are only added when
    set; sending ``null`` for an absent optional would be interpreted by
    Jira as "explicitly clear this field," which is not what callers mean.
    """
    fields: dict[str, Any] = {
        "project": {"key": payload.project_key},
        "summary": payload.summary,
        "issuetype": {"name": payload.issue_type},
    }
    if payload.description:
        fields["description"] = markdown_to_adf(payload.description)
    if payload.assignee_account_id:
        fields["assignee"] = {"accountId": payload.assignee_account_id}
    if payload.priority:
        fields["priority"] = {"name": payload.priority}
    if payload.labels:
        fields["labels"] = list(payload.labels)
    if payload.custom_fields:
        for key, value in payload.custom_fields.items():
            fields[key] = value
    return fields


def _coerce_with_id(value: Any, default_id: str = "0") -> Any:
    """Inject a placeholder id into a nested dict that lacks one.

    Jira returns ids on every entity in production responses, but search
    fixtures and trimmed projections sometimes omit them. The Pydantic
    models in :mod:`jira_mcp.models.jira_entities` mark ``id`` as required
    so a missing id would otherwise crash the parser. We default to the
    string ``"0"`` rather than raising so summary-only views still
    surface useful fields like name and status.
    """
    if isinstance(value, dict):
        coerced = dict(value)
        if "id" not in coerced:
            coerced["id"] = default_id
        # statusCategory shows up under Status; recurse one level so it
        # also gets a default id when missing.
        nested = coerced.get("statusCategory")
        if isinstance(nested, dict) and "id" not in nested:
            nested = dict(nested)
            nested["id"] = 0
            coerced["statusCategory"] = nested
        return coerced
    return value


def _summary_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a raw Jira issue dict into the input shape ``IssueSummary`` accepts."""
    fields = raw.get("fields") or {}
    return {
        "id": raw.get("id"),
        "key": raw.get("key"),
        "summary": fields.get("summary", ""),
        "status": _coerce_with_id(fields.get("status")),
        "assignee": _coerce_with_id(fields.get("assignee")),
        "priority": _coerce_with_id(fields.get("priority")),
        "issuetype": _coerce_with_id(fields.get("issuetype")),
        "updated": fields.get("updated"),
    }


class IssueClient:
    """Domain client for Jira issue operations.

    Composes a :class:`JiraClient` rather than inheriting; the wrapper layer
    does not need any of the HTTP plumbing visible to its callers, and the
    composition keeps the surface area small and easy to mock.
    """

    def __init__(self, jira: JiraClient) -> None:
        """Bind the underlying HTTP client.

        Args:
            jira: A configured :class:`JiraClient`. The client is shared
                with sibling domain clients; do not close it here.
        """
        self._jira = jira

    async def search(
        self,
        jql: str,
        max_results: int = 50,
        fields: list[str] | None = None,
        start_at: int = 0,
    ) -> SearchIssuesOutput:
        """Run a JQL search and return a page of issue summaries.

        Args:
            jql: The JQL expression to evaluate.
            max_results: Page size; Jira caps at 100 for v3 search.
            fields: Optional list of field ids to project; ``None`` lets
                Jira pick its default navigable set.
            start_at: Zero-based offset for pagination.
        """
        params: dict[str, Any] = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
        }
        field_param = _summary_field_set(fields)
        if field_param is not None:
            params["fields"] = field_param
        body = await self._jira.get("/rest/api/3/search", params=params)
        raw_issues = body.get("issues") or []
        issues: list[IssueSummary] = []
        for raw in raw_issues:
            merged = _summary_payload(raw)
            issues.append(IssueSummary.model_validate(merged))
        return SearchIssuesOutput(
            issues=issues,
            total=int(body.get("total", len(issues))),
            start_at=int(body.get("startAt", start_at)),
            max_results=int(body.get("maxResults", max_results)),
        )

    async def get(self, key: str, expand: list[str] | None = None) -> Issue:
        """Fetch a single issue and parse it via :meth:`Issue.from_api`.

        Args:
            key: Issue key (case-insensitive in Jira).
            expand: Optional ``expand`` query list (e.g. ``["transitions"]``).
        """
        params: dict[str, Any] | None = None
        if expand:
            params = {"expand": ",".join(expand)}
        body = await self._jira.get(f"/rest/api/3/issue/{key}", params=params)
        return Issue.from_api(body)

    async def create(self, payload: CreateIssueInput) -> CreateIssueOutput:
        """Create a single Jira issue.

        Args:
            payload: Validated create-issue input.

        Returns:
            The new issue's key, numeric id, and canonical self URL.
        """
        body = {"fields": _build_create_fields(payload)}
        resp = await self._jira.post("/rest/api/3/issue", json=body)
        return CreateIssueOutput(
            key=str(resp.get("key", "")),
            id=str(resp.get("id", "")),
            self_url=str(resp.get("self", "")),
        )

    async def update(self, key: str, fields: dict[str, Any]) -> UpdateIssueOutput:
        """Apply a partial update to an issue.

        Args:
            key: Issue key to update.
            fields: Pre-shaped Jira fields envelope; the caller is
                responsible for ADF-wrapping any rich-text values.
        """
        await self._jira.put(f"/rest/api/3/issue/{key}", json={"fields": fields})
        return UpdateIssueOutput(key=key, updated=True)

    async def transition(
        self,
        key: str,
        transition_id: str,
        comment: str | None = None,
    ) -> TransitionIssueOutput:
        """Move an issue through one workflow transition.

        Args:
            key: Issue key to transition.
            transition_id: Numeric transition id from :meth:`list_transitions`.
            comment: Optional comment to attach atomically with the
                transition; converted to ADF before being placed in the
                ``update.comment.add`` block.
        """
        body: dict[str, Any] = {"transition": {"id": transition_id}}
        if comment:
            body["update"] = {
                "comment": [{"add": {"body": markdown_to_adf(comment)}}]
            }
        await self._jira.post(f"/rest/api/3/issue/{key}/transitions", json=body)
        return TransitionIssueOutput(key=key, new_status=None)

    async def bulk_create(
        self, issues: list[BulkCreateItem]
    ) -> BulkCreateIssuesOutput:
        """Create up to :data:`_BULK_CREATE_CAP` issues in one call.

        On a fully successful bulk POST, every row is reported as a success.
        If Jira reports any rejected rows, this method falls back to
        per-item creates with bounded concurrency so partial successes are
        preserved and individual error messages are reported back.
        """
        capped = list(issues)[:_BULK_CREATE_CAP]
        body = {
            "issueUpdates": [{"fields": _build_create_fields(item)} for item in capped]
        }
        resp = await self._jira.post("/rest/api/3/issue/bulk", json=body)
        errors = resp.get("errors") or []
        created = resp.get("issues") or []
        if not errors and len(created) == len(capped):
            results = [
                BulkCreateResultItem(
                    index=i, key=str(created[i].get("key", "")), error=None
                )
                for i in range(len(capped))
            ]
            return BulkCreateIssuesOutput(results=results)
        return await self._fallback_per_item_create(capped)

    async def _fallback_per_item_create(
        self, items: list[BulkCreateItem]
    ) -> BulkCreateIssuesOutput:
        """Per-item create path used when bulk reports any rejection.

        Bounded by a semaphore so we never burn through the rate-limit
        budget on a 50-item batch. Each row reports its own outcome so a
        single bad input does not poison the whole response.
        """
        sem = asyncio.Semaphore(_FALLBACK_CONCURRENCY)

        async def _one(idx: int, item: BulkCreateItem) -> BulkCreateResultItem:
            async with sem:
                try:
                    out = await self.create(_bulk_item_to_create_input(item))
                except Exception as exc:
                    return BulkCreateResultItem(index=idx, key=None, error=str(exc))
                return BulkCreateResultItem(index=idx, key=out.key, error=None)

        results = await asyncio.gather(
            *[_one(i, it) for i, it in enumerate(items)]
        )
        return BulkCreateIssuesOutput(results=list(results))

    async def add_comment(self, key: str, body: str) -> AddCommentOutput:
        """Append an ADF-wrapped comment to an issue."""
        payload = {"body": markdown_to_adf(body)}
        resp = await self._jira.post(
            f"/rest/api/3/issue/{key}/comment", json=payload
        )
        return AddCommentOutput(
            id=str(resp.get("id", "")),
            created=resp.get("created"),
        )

    async def link(
        self, from_key: str, to_key: str, link_type: str
    ) -> LinkIssuesOutput:
        """Create an issue link of the given type.

        Args:
            from_key: Inward issue key.
            to_key: Outward issue key.
            link_type: Tenant-defined link type name (e.g. ``"Blocks"``).
        """
        body = {
            "type": {"name": link_type},
            "inwardIssue": {"key": from_key},
            "outwardIssue": {"key": to_key},
        }
        await self._jira.post("/rest/api/3/issueLink", json=body)
        return LinkIssuesOutput(linked=True)

    async def list_transitions(self, key: str) -> ListTransitionsOutput:
        """List the workflow transitions the caller may execute right now."""
        resp = await self._jira.get(f"/rest/api/3/issue/{key}/transitions")
        raw = resp.get("transitions") or []
        transitions = [Transition.model_validate(t) for t in raw]
        return ListTransitionsOutput(transitions=transitions)

    async def delete(self, key: str) -> dict[str, Any]:
        """Delete an issue. The tool layer gates this behind an opt-in flag.

        Returns:
            The Jira response body. Jira returns 204 No Content on success,
            which this client surfaces as an empty dict; on failure a typed
            error from the HTTP layer is raised before this point.
        """
        return await self._jira.delete(f"/rest/api/3/issue/{key}")


# Public alias for the input-row model so callers do not have to know the
# tool_io module name; matches the type used in the contract.
BulkCreateItem = BulkCreateIssueItem


def _bulk_item_to_create_input(item: BulkCreateIssueItem) -> CreateIssueInput:
    """Project a bulk-row into the single-create input shape."""
    return CreateIssueInput(
        project_key=item.project_key,
        summary=item.summary,
        issue_type=item.issue_type,
        description=item.description,
        assignee_account_id=item.assignee_account_id,
        priority=item.priority,
        labels=item.labels,
        custom_fields=item.custom_fields,
    )


__all__ = ["BulkCreateItem", "IssueClient", "markdown_to_adf"]
