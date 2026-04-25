"""Helpers for building JQL safely.

JQL injection is real: a project key that happens to contain a quote can
silently change the meaning of a search. Every value that originates from a
user or from data goes through ``escape_jql_string`` before being inserted
into a clause.

The ``Jql`` builder is a small fluent class rather than a string template so
callers cannot accidentally forget the escape step; ``where(clause)`` takes
fragments produced by the helpers below, and ``build()`` joins them with
``AND``.
"""

from __future__ import annotations

from collections.abc import Iterable

# JQL string literals use double quotes; backslash and double-quote are the
# only characters that need escaping per Atlassian's JQL grammar.
_JQL_ESCAPE_TABLE = str.maketrans(
    {
        "\\": "\\\\",
        '"': '\\"',
    }
)


def escape_jql_string(value: str) -> str:
    """Return ``value`` wrapped in double quotes and JQL-escaped.

    Args:
        value: Raw user input or data value.

    Returns:
        A JQL string literal safe to splice into a clause.

    Why not single quotes: Jira accepts both, but double quotes are the
    documented canonical form and play nicer with values that contain
    apostrophes (which appear in display names regularly).
    """
    return f'"{value.translate(_JQL_ESCAPE_TABLE)}"'


def _format_list(values: Iterable[str]) -> str:
    """Format a sequence of values as a JQL ``(...)`` list expression."""
    items = ", ".join(escape_jql_string(v) for v in values)
    return f"({items})"


def assignees_in(emails: Iterable[str]) -> str:
    """Build an ``assignee in (...)`` clause from a list of email addresses.

    Jira accepts emails as user identifiers when GDPR-mode user lookup is
    not enforced; for tenants that require accountIds, callers should
    resolve first and substitute a different builder.
    """
    return f"assignee in {_format_list(emails)}"


def status_in(statuses: Iterable[str]) -> str:
    """Build a ``status in (...)`` clause from status names."""
    return f"status in {_format_list(statuses)}"


def project_eq(key: str) -> str:
    """Build a ``project = "KEY"`` clause.

    Equality (rather than ``in``) is used because a single project is the
    common case and equality is faster to plan on the Jira side.
    """
    return f"project = {escape_jql_string(key)}"


def updated_before(days: int) -> str:
    """Build an ``updated < -Nd`` clause.

    Args:
        days: Non-negative integer number of days. Zero is allowed and
            translates to "updated before now," which is a degenerate but
            valid clause some callers use for symmetry.

    Returns:
        A JQL fragment using Jira's relative date arithmetic.

    Why ``-Nd`` rather than an absolute timestamp: Jira evaluates relative
    dates against the server clock, which avoids client-server clock skew
    issues when running these queries from a different timezone.
    """
    if days < 0:
        raise ValueError("days must be non-negative")
    return f"updated < -{days}d"


class Jql:
    """Fluent builder that joins JQL clauses with ``AND``.

    Chosen over string concatenation because forgetting a separator or
    parenthesizing wrong is easy and silent; this class makes both
    impossible by construction. Each ``where`` call appends one clause;
    ``build`` returns the final expression.
    """

    def __init__(self) -> None:
        self._clauses: list[str] = []
        self._order_by: str | None = None

    def where(self, clause: str) -> Jql:
        """Append a clause. Empty or whitespace-only clauses are ignored.

        Args:
            clause: A JQL fragment, typically produced by one of the
                helper functions in this module.

        Returns:
            Self, so calls can be chained.
        """
        stripped = clause.strip()
        if stripped:
            self._clauses.append(stripped)
        return self

    def order_by(self, expression: str) -> Jql:
        """Set an ``ORDER BY`` suffix.

        Args:
            expression: An order expression like ``updated DESC``. Not
                escaped; callers must not pass user input here.

        Returns:
            Self, so calls can be chained.
        """
        self._order_by = expression.strip() or None
        return self

    def build(self) -> str:
        """Return the assembled JQL string.

        Returns:
            The clauses joined by ``AND``, optionally followed by the
            ``ORDER BY`` clause. An empty builder returns an empty string,
            which Jira treats as "match everything" on most endpoints.
        """
        body = " AND ".join(f"({c})" for c in self._clauses) if self._clauses else ""
        if self._order_by:
            return f"{body} ORDER BY {self._order_by}".strip()
        return body


__all__ = [
    "Jql",
    "assignees_in",
    "escape_jql_string",
    "project_eq",
    "status_in",
    "updated_before",
]
