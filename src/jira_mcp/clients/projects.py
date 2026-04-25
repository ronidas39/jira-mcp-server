"""Project domain client.

Wraps :class:`JiraClient` with project-shaped helpers so that callers receive
typed :class:`Project` instances instead of raw JSON dicts. The split between
this module and ``jira.py`` keeps HTTP concerns (auth, retries, status
mapping) separate from domain shaping.

Endpoints exercised here:

* ``GET /rest/api/3/project``: simple project list. Jira returns up to 50
  rows by default and silently truncates above that, so we fall back to the
  paged ``/project/search`` endpoint when the simple list looks suspiciously
  full.
* ``GET /rest/api/3/project/{key}``: single project with expansions for
  issue types and components.
* ``GET /rest/api/3/field``: every field on the tenant. We filter to entries
  where ``schema.custom`` is true so callers get a clean id-to-name mapping
  for custom fields without having to filter system fields themselves.
"""

from __future__ import annotations

from typing import Any, cast

from ..models.jira_entities import Project
from ..models.tool_io import CustomFieldDescriptor, ListCustomFieldsOutput
from .jira import JiraClient

# Jira's simple project endpoint truncates at this size by default. When we
# see exactly this many rows, switch to the paginated ``/project/search``
# endpoint to avoid silently dropping projects on large tenants.
_SIMPLE_LIST_THRESHOLD = 50

# Page size for ``/project/search``. Jira accepts up to 50; we use the cap so
# tenants with many projects fetch in the fewest round trips.
_SEARCH_PAGE_SIZE = 50


class ProjectClient:
    """Project-shaped operations on top of :class:`JiraClient`."""

    def __init__(self, jira: JiraClient) -> None:
        """Bind to a shared :class:`JiraClient`.

        Args:
            jira: Configured Jira HTTP client. The same instance is reused
                across calls so connection pooling and retry budgets stay
                consistent across the process.
        """
        self._jira = jira

    async def list_projects(self) -> list[Project]:
        """Return every project visible to the authenticated user.

        Tries the simple ``/rest/api/3/project`` endpoint first because the
        response is small and avoids a paginated round trip on small tenants.
        When that endpoint returns the truncation threshold worth of rows,
        we cannot trust it to be complete, so the call falls back to the
        paginated ``/rest/api/3/project/search`` endpoint and walks every
        page.

        Returns:
            Projects parsed into :class:`Project`. Order matches Jira's
            response order, which is unspecified.
        """
        # The simple list endpoint returns a JSON array, but ``request`` is
        # typed as dict[str, Any] for the common case; cast to keep mypy
        # happy without weakening the public client typing.
        simple = cast(Any, await self._jira.get("/rest/api/3/project"))
        rows: list[dict[str, Any]] = (
            simple if isinstance(simple, list) else simple.get("values") or []
        )
        if len(rows) < _SIMPLE_LIST_THRESHOLD:
            return [Project.model_validate(row) for row in rows]
        return await self._list_via_search()

    async def _list_via_search(self) -> list[Project]:
        """Walk ``/project/search`` until ``isLast`` is true."""
        out: list[Project] = []
        start_at = 0
        while True:
            page = await self._jira.get(
                "/rest/api/3/project/search",
                params={"startAt": start_at, "maxResults": _SEARCH_PAGE_SIZE},
            )
            values: list[dict[str, Any]] = page.get("values") or []
            out.extend(Project.model_validate(v) for v in values)
            if page.get("isLast", True) or not values:
                return out
            start_at += len(values)

    async def get(self, key: str) -> Project:
        """Fetch a single project by key or numeric id.

        Issue types and components are requested via ``expand`` because both
        are needed by tools that build issue creation forms; fetching them up
        front saves a separate round trip per project view.

        Args:
            key: Project key (``"PROJ"``) or numeric id (``"10000"``).

        Returns:
            The hydrated :class:`Project`.
        """
        payload = await self._jira.get(
            f"/rest/api/3/project/{key}",
            params={"expand": "issueTypes,components"},
        )
        return Project.model_validate(payload)

    async def list_custom_fields(self) -> ListCustomFieldsOutput:
        """Return tenant-defined custom fields with id-to-name mapping.

        Jira's ``/rest/api/3/field`` endpoint returns every field, system or
        custom. The MCP surface only cares about custom fields because system
        fields already have stable model attributes; mixing them in would
        bloat the response and confuse the model when it is picking which
        ``customfield_*`` id to set.

        Returns:
            A :class:`ListCustomFieldsOutput` whose ``fields`` list contains
            one descriptor per custom field, sorted by id for stable output.
        """
        # ``/rest/api/3/field`` returns a JSON array at the top level; cast
        # so the list-shaped branch type-checks under strict mypy.
        payload = cast(Any, await self._jira.get("/rest/api/3/field"))
        rows: list[dict[str, Any]] = (
            payload if isinstance(payload, list) else payload.get("values") or []
        )
        descriptors: list[CustomFieldDescriptor] = []
        for row in rows:
            schema = row.get("schema") or {}
            if not schema.get("custom"):
                continue
            descriptors.append(
                CustomFieldDescriptor(
                    id=str(row.get("id")),
                    name=str(row.get("name") or ""),
                    custom=True,
                    schema_type=schema.get("type"),
                )
            )
        descriptors.sort(key=lambda d: d.id)
        return ListCustomFieldsOutput(fields=descriptors)


__all__ = ["ProjectClient"]
