"""MCP tool handlers for the sprint and board domain.

Each tool is a small async coroutine that validates its inputs against a
Pydantic model, calls into :class:`SprintClient`, and returns a JSON-mode
``model_dump`` of the matching output model. Write tools (currently only
``move_to_sprint``) record an :class:`AuditRepository` row before returning,
so an operator can reconstruct who moved what and when from the audit log
alone.

The module exposes three registration surfaces:
    * :data:`SPRINT_TOOLS` -- the :class:`mcp.types.Tool` descriptors the
      server publishes via ``list_tools``.
    * :func:`build_sprint_dispatch` -- builds the ``name -> handler`` map
      the server's ``call_tool`` handler indexes into.
    * :func:`register` -- the bootstrap-friendly entry point that returns
      both descriptor list and handler map keyed by tool name, matching
      the surface the issue and project tool groups expose.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp import types

from ..clients.sprints import SprintClient
from ..db.repositories.audit import AuditRepository
from ..models.tool_io import (
    GetSprintInput,
    GetSprintOutput,
    ListBoardsInput,
    ListBoardsOutput,
    ListSprintsInput,
    ListSprintsOutput,
    MoveToSprintInput,
    MoveToSprintOutput,
    SprintReportInput,
    SprintReportOutput,
)

# Try to share the actor and correlation contextvars with the rest of the
# server. If the module has not landed yet (parallel build), fall back to a
# fresh uuid and the literal "unknown" actor so audit rows stay well-formed.
try:
    from ..utils.correlation import (
        get_actor as _ctx_get_actor,
    )
    from ..utils.correlation import (
        get_or_new_correlation_id as _ctx_get_correlation_id,
    )

    def _get_actor() -> str:
        return _ctx_get_actor()

    def _get_correlation_id() -> str:
        return _ctx_get_correlation_id()
except ImportError:  # pragma: no cover - exercised only when correlation.py is absent

    def _get_actor() -> str:
        return "unknown"

    def _get_correlation_id() -> str:
        return uuid.uuid4().hex


Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


SPRINT_TOOLS: list[types.Tool] = [
    types.Tool(
        name="list_boards",
        description=(
            "List Jira agile boards visible to the caller. Pass project_key "
            "to scope to one project. Use this before list_sprints when the "
            "caller does not already know a board id."
        ),
        inputSchema=ListBoardsInput.model_json_schema(),
        outputSchema=ListBoardsOutput.model_json_schema(),
    ),
    types.Tool(
        name="list_sprints",
        description=(
            "List sprints on an agile board. Filter by state ('future', "
            "'active', 'closed'). Use this to find the active sprint for "
            "stand-up summaries or to enumerate completed sprints for "
            "velocity reports."
        ),
        inputSchema=ListSprintsInput.model_json_schema(),
        outputSchema=ListSprintsOutput.model_json_schema(),
    ),
    types.Tool(
        name="get_sprint",
        description=(
            "Fetch a single sprint by id. Returns name, state, dates, and "
            "goal. Use when the caller has a sprint id in hand and needs "
            "the full record for context."
        ),
        inputSchema=GetSprintInput.model_json_schema(),
        outputSchema=GetSprintOutput.model_json_schema(),
    ),
    types.Tool(
        name="move_to_sprint",
        description=(
            "Move a list of issues into a sprint. Writes are batched at "
            "Jira's 50-key per-request ceiling and every call is recorded "
            "in the audit log. Confirm the sprint is in the expected state "
            "before invoking; Jira will reject moves into closed sprints."
        ),
        inputSchema=MoveToSprintInput.model_json_schema(),
        outputSchema=MoveToSprintOutput.model_json_schema(),
    ),
    types.Tool(
        name="sprint_report",
        description=(
            "Synthesise a sprint report: committed (approximated from "
            "current scope), delivered (status category 'done'), and "
            "at_risk (active sprints past end date). See the output model "
            "docstring for the precise approximation policy."
        ),
        inputSchema=SprintReportInput.model_json_schema(),
        outputSchema=SprintReportOutput.model_json_schema(),
    ),
]


def _hash_input(payload: dict[str, Any]) -> str:
    """Deterministic SHA-256 hex digest of a JSON-encoded input.

    Audit rows store this so identical inputs produce identical hashes
    across restarts, which makes deduplication queries against the audit
    log straightforward.
    """
    serialised = json.dumps(payload, sort_keys=True, default=str)
    # Audit fingerprinting is not a security boundary, so SHA-256 is used
    # only for its stable hex shape, not for any cryptographic property.
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


async def _list_boards_handler(args: dict[str, Any], client: SprintClient) -> dict[str, Any]:
    payload = ListBoardsInput.model_validate(args)
    boards = await client.list_boards(project_key=payload.project_key)
    return ListBoardsOutput(boards=boards).model_dump(mode="json", by_alias=True)


async def _list_sprints_handler(args: dict[str, Any], client: SprintClient) -> dict[str, Any]:
    payload = ListSprintsInput.model_validate(args)
    sprints = await client.list_sprints(board_id=payload.board_id, state=payload.state)
    return ListSprintsOutput(sprints=sprints).model_dump(mode="json", by_alias=True)


async def _get_sprint_handler(args: dict[str, Any], client: SprintClient) -> dict[str, Any]:
    payload = GetSprintInput.model_validate(args)
    sprint = await client.get_sprint(payload.sprint_id)
    return GetSprintOutput(sprint=sprint).model_dump(mode="json", by_alias=True)


async def _sprint_report_handler(args: dict[str, Any], client: SprintClient) -> dict[str, Any]:
    payload = SprintReportInput.model_validate(args)
    report = await client.sprint_report(payload.sprint_id)
    return report.model_dump(mode="json", by_alias=True)


async def _move_to_sprint_handler(
    args: dict[str, Any],
    client: SprintClient,
    audit: AuditRepository,
) -> dict[str, Any]:
    """Move issues into a sprint and record an audit row in the same call.

    The audit row is written after the Jira call so a network-level failure
    is captured as ``response_status='error'`` rather than leaving an
    optimistic success row in the log.
    """
    payload = MoveToSprintInput.model_validate(args)
    correlation_id = _get_correlation_id()
    actor = _get_actor()
    started = time.perf_counter()
    status = "ok"
    moved = 0
    try:
        result = await client.move_to_sprint(
            issue_keys=payload.issue_keys, sprint_id=payload.sprint_id
        )
        moved = result["moved_count"]
    except Exception:
        status = "error"
        raise
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        await audit.record(
            tool="move_to_sprint",
            input_hash=_hash_input(payload.model_dump(mode="json", by_alias=True)),
            input_summary={
                "sprint_id": payload.sprint_id,
                "issue_keys": payload.issue_keys,
            },
            response_status=status,
            jira_id=str(payload.sprint_id),
            actor=actor,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )
    return MoveToSprintOutput(moved_count=moved).model_dump(mode="json", by_alias=True)


def build_sprint_dispatch(client: SprintClient, audit: AuditRepository) -> dict[str, Handler]:
    """Return the ``name -> handler`` map the server dispatch uses.

    Args:
        client: Configured :class:`SprintClient`.
        audit: Audit repository the write tools record into.

    Returns:
        A mapping from MCP tool name to an async handler that accepts the
        raw arguments dict and returns the output payload as a plain dict.
    """

    async def _list_boards(args: dict[str, Any]) -> dict[str, Any]:
        return await _list_boards_handler(args, client)

    async def _list_sprints(args: dict[str, Any]) -> dict[str, Any]:
        return await _list_sprints_handler(args, client)

    async def _get_sprint(args: dict[str, Any]) -> dict[str, Any]:
        return await _get_sprint_handler(args, client)

    async def _move_to_sprint(args: dict[str, Any]) -> dict[str, Any]:
        return await _move_to_sprint_handler(args, client, audit)

    async def _sprint_report(args: dict[str, Any]) -> dict[str, Any]:
        return await _sprint_report_handler(args, client)

    return {
        "list_boards": _list_boards,
        "list_sprints": _list_sprints,
        "get_sprint": _get_sprint,
        "move_to_sprint": _move_to_sprint,
        "sprint_report": _sprint_report,
    }


@dataclass(slots=True)
class SprintToolContext:
    """Bound dependencies for the sprint tools.

    Carrying these as a dataclass rather than positional args means the
    bootstrap can extend the context (e.g. adding a settings handle) later
    without touching the registration call sites.
    """

    sprints: SprintClient
    audit: AuditRepository


def register(server: object, ctx: SprintToolContext) -> dict[str, tuple[types.Tool, Handler]]:
    """Build the sprint tool registry the bootstrap installs on the server.

    The MCP SDK ``Server`` only allows a single ``list_tools`` and
    ``call_tool`` handler per instance, so per-module decorators would
    clobber one another. The bootstrap therefore composes the global
    handlers from each group's registry. ``server`` is accepted for
    signature parity with the other tool groups; this group does not
    install any decorators of its own.

    Args:
        server: The MCP :class:`Server` (unused here, kept for parity).
        ctx: Bound :class:`SprintClient` and :class:`AuditRepository`.

    Returns:
        Map from tool name to ``(Tool, handler)`` so the bootstrap can
        merge it with the other groups' registries.
    """
    del server  # Retained in the signature for uniform bootstrap wiring.
    dispatch = build_sprint_dispatch(ctx.sprints, ctx.audit)
    by_name = {tool.name: tool for tool in SPRINT_TOOLS}
    registry: dict[str, tuple[types.Tool, Handler]] = {}
    for name, handler in dispatch.items():
        registry[name] = (by_name[name], handler)
    return registry


__all__ = [
    "SPRINT_TOOLS",
    "SprintToolContext",
    "build_sprint_dispatch",
    "register",
]
