"""Issue-domain MCP tools.

This module wires the :class:`IssueClient` into MCP tool handlers and
registers them on the SDK's :class:`Server`. Each public tool has a
Pydantic input model and a Pydantic output model from
:mod:`jira_mcp.models.tool_io`; descriptions are written for the model that
will be choosing among tools, not for human readers, so the wording leans
toward "when to use" rather than narrative prose.

Every write tool emits one row to the audit log via
:meth:`AuditRepository.record`. The dispatcher hashes the canonical-JSON
input, trims long description bodies, and records the duration so audit
queries can answer both "who did what" and "where is the latency."
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp import types
from mcp.server import Server
from pydantic import BaseModel

from ..clients.issues import IssueClient, markdown_to_adf
from ..config.settings import Settings
from ..db.repositories.audit import AuditRepository
from ..models.tool_io import (
    AddCommentInput,
    AddCommentOutput,
    BulkCreateIssuesInput,
    BulkCreateIssuesOutput,
    CreateIssueInput,
    CreateIssueOutput,
    GetIssueInput,
    GetIssueOutput,
    LinkIssuesInput,
    LinkIssuesOutput,
    ListTransitionsInput,
    ListTransitionsOutput,
    SearchIssuesInput,
    SearchIssuesOutput,
    TransitionIssueInput,
    TransitionIssueOutput,
    UpdateIssueInput,
    UpdateIssueOutput,
)
from ..utils.correlation import get_actor, get_or_new_correlation_id

# Threshold above which a free-text description is replaced with a length
# marker in the audit summary. Keeps audit rows compact without losing the
# fact that a body was sent.
_DESCRIPTION_TRIM_LIMIT = 500


@dataclass(slots=True)
class IssueToolContext:
    """Bundle of dependencies the issue tools need.

    Passed in at registration time rather than reached for via globals so
    tests can stand up a single tool with mock collaborators without
    booting the whole server.
    """

    issues: IssueClient
    audit: AuditRepository
    settings: Settings


def _trim_input_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with long ``description``/``body`` fields shortened.

    Args:
        payload: The raw arguments dict the dispatcher received.

    Returns:
        A new dict; if no trimming is needed, the keys still come through a
        copy so callers may not mutate the original via the return value.
    """
    summary = dict(payload)
    for key in ("description", "body"):
        value = summary.get(key)
        if isinstance(value, str) and len(value) > _DESCRIPTION_TRIM_LIMIT:
            summary[key] = f"<trimmed:{len(value)}chars>"
    return summary


def _hash_input(payload: dict[str, Any]) -> str:
    """SHA-256 over a canonical JSON dump of the payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    """Render a Pydantic model to the JSON schema MCP expects."""
    return model.model_json_schema()


# Tool registry: each row carries the description (written for the LLM
# choosing among tools), input model, and output model. Keeping all three
# columns in one table makes the registration loop trivial and removes the
# two parallel dicts that previously had to be kept in sync.
_TOOLS: dict[str, tuple[str, type[BaseModel], type[BaseModel]]] = {
    "search_issues": (
        "Run a JQL search and return a page of issue summaries. Use this "
        "when the caller wants a list view; for a single known key, use "
        "get_issue instead. Always page; do not pull more than 100 issues "
        "in one call.",
        SearchIssuesInput,
        SearchIssuesOutput,
    ),
    "get_issue": (
        "Fetch one issue by key with optional comments and transitions. "
        "Prefer this over search_issues when the key is known.",
        GetIssueInput,
        GetIssueOutput,
    ),
    "create_issue": (
        "Create one Jira issue. Description is plain text; the server "
        "wraps it in ADF before sending. For more than one issue at a "
        "time, prefer bulk_create_issues.",
        CreateIssueInput,
        CreateIssueOutput,
    ),
    "update_issue": (
        "Apply a partial update to an issue. Only fields that are set are "
        "sent; null leaves the field alone. To unassign, pass an empty "
        "string for assignee_account_id.",
        UpdateIssueInput,
        UpdateIssueOutput,
    ),
    "transition_issue": (
        "Move an issue through one workflow transition. Always call "
        "list_transitions first; transition ids vary per workflow.",
        TransitionIssueInput,
        TransitionIssueOutput,
    ),
    "bulk_create_issues": (
        "Create up to 50 issues in one batch. On any rejected row the "
        "server falls back to per-item creates so partial success is "
        "preserved.",
        BulkCreateIssuesInput,
        BulkCreateIssuesOutput,
    ),
    "add_comment": (
        "Append a comment to an issue. Body is plain text; the server "
        "wraps it in ADF before posting.",
        AddCommentInput,
        AddCommentOutput,
    ),
    "link_issues": (
        "Create an issue link of the given type. Link type names are "
        "tenant-specific; verify against the Jira admin if unsure.",
        LinkIssuesInput,
        LinkIssuesOutput,
    ),
    "list_transitions": (
        "List the workflow transitions the caller may execute on this "
        "issue right now. Required before transition_issue because "
        "transition ids are not stable across workflows.",
        ListTransitionsInput,
        ListTransitionsOutput,
    ),
    "delete_issue": (
        "Delete an issue. Disabled by default; the operator must opt in "
        "via the allow_delete_issues setting before this tool will run.",
        GetIssueInput,
        UpdateIssueOutput,
    ),
}


def _build_tool_definitions() -> list[types.Tool]:
    """Construct the SDK Tool objects from the registry table."""
    return [
        types.Tool(
            name=name,
            description=desc,
            inputSchema=_schema(in_model),
            outputSchema=_schema(out_model),
        )
        for name, (desc, in_model, out_model) in _TOOLS.items()
    ]


# Tools that mutate Jira state and therefore produce audit rows. ``get_issue``,
# ``search_issues``, and ``list_transitions`` are read-only and skip the audit.
_WRITE_TOOLS = {
    "create_issue",
    "update_issue",
    "transition_issue",
    "bulk_create_issues",
    "add_comment",
    "link_issues",
    "delete_issue",
}


async def _dispatch(ctx: IssueToolContext, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route a validated tool call to the right handler.

    Audit rows are written for every write tool, even on failure: a tool
    that raises has still produced an attempt that compliance wants to
    see. The duration is measured around the handler so the audit row
    captures the wire latency, not just the success path.
    """
    handler = _HANDLERS[name]
    started = time.perf_counter()
    correlation_id = get_or_new_correlation_id()
    response_status = "ok"
    jira_id: str | None = None
    try:
        result = await handler(ctx, arguments)
        jira_id = _extract_jira_id(name, result)
        return result
    except Exception:
        response_status = "error"
        raise
    finally:
        if name in _WRITE_TOOLS:
            duration_ms = int((time.perf_counter() - started) * 1000)
            await ctx.audit.record(
                tool=name,
                input_hash=_hash_input(arguments),
                input_summary=_trim_input_summary(arguments),
                response_status=response_status,
                jira_id=jira_id,
                actor=get_actor(),
                duration_ms=duration_ms,
                correlation_id=correlation_id,
            )


def _extract_jira_id(name: str, result: dict[str, Any]) -> str | None:
    """Pick the most informative identifier out of a tool result, if any."""
    if name == "create_issue":
        return str(result.get("key") or result.get("id") or "") or None
    if name in {"update_issue", "transition_issue", "delete_issue"}:
        return str(result.get("key") or "") or None
    if name == "add_comment":
        return str(result.get("id") or "") or None
    return None


# Per-tool handlers. Each takes the validated raw dict and returns a dict
# matching the registered output schema; the dispatcher records audit rows
# around the handler boundary.


async def _h_search(ctx: IssueToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    p = SearchIssuesInput.model_validate(raw)
    out = await ctx.issues.search(
        jql=p.jql, max_results=p.max_results, fields=p.fields, start_at=p.start_at
    )
    return out.model_dump(mode="json", by_alias=True)


async def _h_get(ctx: IssueToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    p = GetIssueInput.model_validate(raw)
    expand: list[str] = []
    if p.expand_comments:
        expand.append("renderedFields")
    if p.expand_transitions:
        expand.append("transitions")
    issue = await ctx.issues.get(p.key, expand=expand or None)
    return GetIssueOutput(issue=issue).model_dump(mode="json", by_alias=True)


async def _h_create(ctx: IssueToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    out = await ctx.issues.create(CreateIssueInput.model_validate(raw))
    return out.model_dump(mode="json", by_alias=True)


def _build_update_fields(p: UpdateIssueInput) -> dict[str, Any]:
    """Translate an UpdateIssueInput into the Jira fields envelope."""
    fields: dict[str, Any] = {}
    if p.summary is not None:
        fields["summary"] = p.summary
    if p.description is not None:
        fields["description"] = markdown_to_adf(p.description)
    if p.assignee_account_id is not None:
        fields["assignee"] = (
            None if p.assignee_account_id == "" else {"accountId": p.assignee_account_id}
        )
    if p.priority is not None:
        fields["priority"] = {"name": p.priority}
    if p.labels is not None:
        fields["labels"] = list(p.labels)
    if p.custom_fields:
        fields.update(p.custom_fields)
    return fields


async def _h_update(ctx: IssueToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    p = UpdateIssueInput.model_validate(raw)
    out = await ctx.issues.update(p.key, _build_update_fields(p))
    return out.model_dump(mode="json", by_alias=True)


async def _h_transition(ctx: IssueToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    p = TransitionIssueInput.model_validate(raw)
    out = await ctx.issues.transition(key=p.key, transition_id=p.transition_id, comment=p.comment)
    return out.model_dump(mode="json", by_alias=True)


async def _h_bulk_create(ctx: IssueToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    p = BulkCreateIssuesInput.model_validate(raw)
    out = await ctx.issues.bulk_create(list(p.issues))
    return out.model_dump(mode="json", by_alias=True)


async def _h_add_comment(ctx: IssueToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    p = AddCommentInput.model_validate(raw)
    out = await ctx.issues.add_comment(p.key, p.body)
    return out.model_dump(mode="json", by_alias=True)


async def _h_link(ctx: IssueToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    p = LinkIssuesInput.model_validate(raw)
    out = await ctx.issues.link(from_key=p.inward_key, to_key=p.outward_key, link_type=p.link_type)
    return out.model_dump(mode="json", by_alias=True)


async def _h_list_transitions(ctx: IssueToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    p = ListTransitionsInput.model_validate(raw)
    out = await ctx.issues.list_transitions(p.key)
    return out.model_dump(mode="json", by_alias=True)


async def _h_delete(ctx: IssueToolContext, raw: dict[str, Any]) -> dict[str, Any]:
    if not ctx.settings.allow_delete_issues:
        raise PermissionError("delete_issue is disabled; set allow_delete_issues=true to enable.")
    p = GetIssueInput.model_validate(raw)
    await ctx.issues.delete(p.key)
    return UpdateIssueOutput(key=p.key, updated=True).model_dump(mode="json", by_alias=True)


_HandlerType = Callable[[IssueToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]
_HANDLERS: dict[str, _HandlerType] = {
    "search_issues": _h_search,
    "get_issue": _h_get,
    "create_issue": _h_create,
    "update_issue": _h_update,
    "transition_issue": _h_transition,
    "bulk_create_issues": _h_bulk_create,
    "add_comment": _h_add_comment,
    "link_issues": _h_link,
    "list_transitions": _h_list_transitions,
    "delete_issue": _h_delete,
}


ToolEntry = tuple[types.Tool, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]


def register(server: Server, ctx: IssueToolContext) -> dict[str, ToolEntry]:
    """Build and return the issue tool registry the bootstrap installs.

    The MCP SDK ``Server`` only allows a single ``list_tools`` and
    ``call_tool`` handler per instance, so per-module decorators would
    clobber one another. The bootstrap therefore composes the global
    handlers from each tool group's registry. ``server`` is accepted for
    signature parity with the other tool groups; this group does not
    install any decorators of its own.

    Args:
        server: The MCP server instance, kept for parity with other groups.
        ctx: Bound dependencies (issue client, audit repo, settings).

    Returns:
        Map from tool name to ``(Tool, handler)``.
    """
    del server
    tool_defs = {t.name: t for t in _build_tool_definitions()}
    registry: dict[str, ToolEntry] = {}
    for name, tool in tool_defs.items():
        if name not in _HANDLERS:
            continue

        async def _handler(args: dict[str, Any], *, _name: str = name) -> dict[str, Any]:
            return await _dispatch(ctx, _name, args)

        registry[name] = (tool, _handler)
    return registry


__all__ = ["IssueToolContext", "ToolEntry", "register"]
