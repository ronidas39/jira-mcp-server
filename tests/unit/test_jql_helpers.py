"""Unit tests for the JQL helper module.

Pins the escape contract (so unsafe characters cannot smuggle their way
into a clause), the shape of the multi-value helpers, and the
:class:`Jql` builder's join semantics.
"""

from __future__ import annotations

from jira_mcp.utils.jql import (
    Jql,
    escape_jql_string,
    project_eq,
    status_in,
    updated_before,
)


def test_escape_jql_string_handles_double_quotes() -> None:
    """Double quotes inside a value are backslash-escaped."""
    assert escape_jql_string('a "b" c') == '"a \\"b\\" c"'


def test_escape_jql_string_handles_backslashes() -> None:
    """Backslashes are doubled before quotes are escaped."""
    assert escape_jql_string("path\\to\\thing") == '"path\\\\to\\\\thing"'


def test_escape_jql_string_preserves_newlines() -> None:
    """Newlines stay literal; JQL has no special handling for them."""
    assert escape_jql_string("line1\nline2") == '"line1\nline2"'


def test_status_in_single_status_renders_one_element_list() -> None:
    """A one-status filter still produces the (..) list form."""
    assert status_in(["In Progress"]) == 'status in ("In Progress")'


def test_status_in_multiple_statuses_joins_with_comma() -> None:
    """Multiple statuses are comma-joined inside the parenthesised list."""
    out = status_in(["To Do", "In Progress", "Done"])
    assert out == 'status in ("To Do", "In Progress", "Done")'


def test_status_in_escapes_quote_inside_value() -> None:
    """Statuses with embedded quotes do not break the clause."""
    out = status_in(['Needs "review"'])
    assert out == 'status in ("Needs \\"review\\"")'


def test_jql_builder_composes_non_trivial_query() -> None:
    """Multiple where() calls join with AND and ORDER BY appends correctly."""
    jql = (
        Jql()
        .where(project_eq("PROJ"))
        .where(status_in(["To Do", "In Progress"]))
        .where(updated_before(7))
        .order_by("updated ASC")
        .build()
    )
    assert jql == (
        '(project = "PROJ") AND '
        '(status in ("To Do", "In Progress")) AND '
        '(updated < -7d) '
        "ORDER BY updated ASC"
    )


def test_jql_builder_skips_empty_clauses() -> None:
    """Whitespace-only clauses are ignored to avoid stray ANDs."""
    jql = Jql().where(project_eq("PROJ")).where("   ").build()
    assert jql == '(project = "PROJ")'


def test_jql_builder_empty_returns_empty_string() -> None:
    """An unconfigured builder returns an empty string."""
    assert Jql().build() == ""
