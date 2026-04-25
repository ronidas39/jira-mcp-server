"""User domain client.

Wraps :class:`JiraClient` with helpers for the Jira user endpoints. The
notable wrinkle in Jira's user API is that ``/users/search`` returns every
user matching a substring across display name and email, so resolution of a
human label to an ``accountId`` has to disambiguate carefully; the
:meth:`UserClient.resolve` docstring explains the exact policy.

Endpoints exercised here:

* ``GET /rest/api/3/users/search``: substring search across all users.
* ``GET /rest/api/3/user/assignable/search``: substring search restricted to
  users assignable to a project; preferred when the caller is staffing a
  ticket since it filters out former employees and inactive accounts.
* ``GET /rest/api/3/user/search``: exact-prefix search, primarily used to
  locate a user by email address.
* ``GET /rest/api/3/myself``: identity probe used by the lifespan check and
  exposed for tools that need the calling principal.
"""

from __future__ import annotations

from typing import Any, cast

from ..models.jira_entities import User
from .jira import JiraClient


class UserClient:
    """User-shaped operations on top of :class:`JiraClient`."""

    def __init__(self, jira: JiraClient) -> None:
        """Bind to a shared :class:`JiraClient`.

        Args:
            jira: Configured Jira HTTP client. The same instance is reused
                across calls so connection pooling and retry budgets stay
                consistent across the process.
        """
        self._jira = jira

    async def list_users(
        self,
        query: str | None = None,
        project_key: str | None = None,
    ) -> list[User]:
        """List users, optionally filtered by query and project.

        When ``project_key`` is supplied, the call switches to the assignable
        endpoint. That endpoint requires the ``project`` parameter and a
        ``query`` parameter (Jira returns 400 otherwise), so an empty string
        is sent when the caller did not provide one; this matches Jira's
        documented "match all" semantics for that endpoint.

        Args:
            query: Optional substring to filter by display name or email.
            project_key: Optional project key; when provided, only users
                assignable to that project are returned.

        Returns:
            Users parsed into :class:`User`. Order is whatever Jira returns,
            which is unspecified.
        """
        if project_key is not None:
            params: dict[str, Any] = {
                "project": project_key,
                "query": query if query is not None else "",
            }
            payload = cast(
                Any,
                await self._jira.get(
                    "/rest/api/3/user/assignable/search",
                    params=params,
                ),
            )
        else:
            search_params: dict[str, Any] = {}
            if query is not None:
                search_params["query"] = query
            payload = cast(
                Any,
                await self._jira.get(
                    "/rest/api/3/users/search",
                    params=search_params or None,
                ),
            )
        rows: list[dict[str, Any]] = (
            payload if isinstance(payload, list) else payload.get("values") or []
        )
        return [User.model_validate(r) for r in rows]

    async def resolve(self, email_or_displayname: str) -> User | None:
        """Resolve a human label to a Jira :class:`User`.

        Disambiguation policy:

        1. If the input contains an ``@``, treat it as an email and call
           ``/rest/api/3/user/search?query=<email>``. Among the results,
           pick the single record whose ``emailAddress`` matches the input
           exactly, case-insensitive. If zero match or more than one match,
           the email path returns ``None`` rather than guess.
        2. Otherwise, fall back to the same endpoint with the input as the
           query and select on ``displayName``. Match is case-insensitive
           equality. If multiple users share the same ``displayName``, the
           method returns ``None`` because there is no safe basis to pick
           one over another. Display names are not unique in Jira, and
           silently picking the first match is how wrong people get tagged
           on tickets.

        ``None`` is returned in three cases: no API hits, multiple ambiguous
        hits, and the email branch finding no exact match. Callers that need
        a softer match should call :meth:`list_users` and pick interactively.

        Args:
            email_or_displayname: Email address or display name.

        Returns:
            The resolved user, or ``None`` when no unambiguous match exists.
        """
        identifier = email_or_displayname.strip()
        if not identifier:
            return None

        payload = cast(
            Any,
            await self._jira.get(
                "/rest/api/3/user/search",
                params={"query": identifier},
            ),
        )
        rows: list[dict[str, Any]] = (
            payload if isinstance(payload, list) else payload.get("values") or []
        )
        if not rows:
            return None

        if "@" in identifier:
            return self._unique_email_match(rows, identifier)
        return self._unique_displayname_match(rows, identifier)

    @staticmethod
    def _unique_email_match(
        rows: list[dict[str, Any]],
        email: str,
    ) -> User | None:
        """Return the only row whose email matches; ``None`` when ambiguous."""
        target = email.lower()
        matches = [
            r
            for r in rows
            if isinstance(r.get("emailAddress"), str)
            and cast(str, r["emailAddress"]).lower() == target
        ]
        if len(matches) == 1:
            return User.model_validate(matches[0])
        return None

    @staticmethod
    def _unique_displayname_match(
        rows: list[dict[str, Any]],
        display_name: str,
    ) -> User | None:
        """Return the only row whose displayName matches; ``None`` when ambiguous."""
        target = display_name.lower()
        matches = [
            r
            for r in rows
            if isinstance(r.get("displayName"), str)
            and cast(str, r["displayName"]).lower() == target
        ]
        if len(matches) == 1:
            return User.model_validate(matches[0])
        return None

    async def get_self(self) -> User:
        """Return the user identified by the current credentials.

        Used by the lifespan probe to confirm credentials work; exposed here
        so tools can also call it without re-implementing the endpoint.

        Returns:
            The :class:`User` for the authenticated principal.
        """
        payload = await self._jira.get("/rest/api/3/myself")
        return User.model_validate(payload)


__all__ = ["UserClient"]
