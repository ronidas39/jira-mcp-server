"""Application wiring for the Jira MCP server.

This module composes the long-lived dependencies the server needs at runtime:
the auth provider, the shared HTTP client, the Jira client, the Mongo
connection, the audit repository, the domain clients, and the MCP `Server`
instance from the SDK. The result is a frozen `ServerContext` so the rest of
the codebase has a single, immutable handle to pass around.

The `httpx.AsyncClient` is built here, once, and shared. Building it inside
each tool would defeat connection pooling and quietly break the rate-limit
budget Jira Cloud enforces per origin.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from mcp.server import Server

from ..auth.api_token import ApiTokenAuth
from ..auth.provider import AuthProvider
from ..clients.issues import IssueClient
from ..clients.jira import JiraClient
from ..clients.projects import ProjectClient
from ..clients.sprints import SprintClient
from ..clients.users import UserClient
from ..config.settings import Settings
from ..db.connection import MongoConnection
from ..db.repositories.audit import AuditRepository
from ..prompts import register as register_prompts
from ..resources import register as register_resources
from ..tools import register_all as register_all_tools
from ..tools.analytics import AnalyticsToolContext
from ..tools.issues import IssueToolContext
from ..tools.sprints import SprintToolContext
from ..utils.logging import configure_logging, get_logger

_INSTRUCTIONS = (
    "Jira MCP server. Exposes Atlassian Jira Cloud as MCP tools, resources, "
    "and prompts: issue CRUD, JQL search, sprint operations, workflow "
    "transitions, comments, and workload analytics. Prefer structured tool "
    "calls over freeform requests; every write produces an audit log entry."
)


@dataclass(frozen=True, slots=True)
class ServerContext:
    """Immutable bundle of long-lived runtime dependencies.

    Frozen on purpose: nothing downstream should swap a Mongo client or HTTP
    client mid-flight, and a frozen dataclass makes that misuse a hard error
    instead of a silent race.
    """

    server: Server
    jira_client: JiraClient
    issue_client: IssueClient
    project_client: ProjectClient
    user_client: UserClient
    sprint_client: SprintClient
    mongo: MongoConnection
    audit: AuditRepository
    http: httpx.AsyncClient


def _build_auth_provider(settings: Settings) -> AuthProvider:
    """Pick an `AuthProvider` from the configured auth mode.

    OAuth is intentionally a deferred milestone: returning a half-working
    OAuth provider would hide bugs behind a polished surface. Failing fast
    forces the operator to set api_token mode until OAuth lands.
    """
    if settings.jira_auth_mode == "api_token":
        if settings.jira_email is None or settings.jira_api_token is None:
            msg = "api_token mode requires JIRA_EMAIL and JIRA_API_TOKEN"
            raise ValueError(msg)
        return ApiTokenAuth(settings.jira_email, settings.jira_api_token)
    if settings.jira_auth_mode == "oauth":
        msg = "oauth mode lands in M2; use api_token for now"
        raise NotImplementedError(msg)
    msg = f"unsupported jira_auth_mode: {settings.jira_auth_mode!r}"
    raise ValueError(msg)


def create_app(settings: Settings) -> ServerContext:
    """Compose runtime dependencies and return a frozen `ServerContext`.

    Args:
        settings: Validated runtime configuration.

    Returns:
        A `ServerContext` containing every long-lived dependency the server
        needs. Caller is responsible for invoking startup and shutdown
        hooks around the transport's serve loop.

    Raises:
        NotImplementedError: When `jira_auth_mode == "oauth"`. OAuth lands
            in a later milestone and we refuse to start with a stub.
        ValueError: When required settings for the chosen auth mode are
            missing, or when two tool groups try to register the same name.
    """
    configure_logging(settings.log_level)
    log = get_logger("jira_mcp.server.app")

    auth_provider = _build_auth_provider(settings)

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_connections=settings.jira_max_concurrency),
    )

    jira_client = JiraClient(
        base_url=str(settings.jira_base_url),
        auth=auth_provider,
        http=http_client,
        max_retries=settings.jira_max_retries,
    )

    issue_client = IssueClient(jira_client)
    project_client = ProjectClient(jira_client)
    user_client = UserClient(jira_client)
    sprint_client = SprintClient(jira_client)

    mongo = MongoConnection(settings.mongo_uri, settings.mongo_db)
    audit = AuditRepository(mongo.db)

    server = Server(
        name="jira-mcp-server",
        version="0.1.0",
        instructions=_INSTRUCTIONS,
    )

    register_all_tools(
        server,
        issue_ctx=IssueToolContext(issues=issue_client, audit=audit, settings=settings),
        analytics_ctx=AnalyticsToolContext(
            issues=issue_client, jira=jira_client, settings=settings
        ),
        sprint_ctx=SprintToolContext(sprints=sprint_client, audit=audit),
        project_client=project_client,
        user_client=user_client,
    )

    ctx = ServerContext(
        server=server,
        jira_client=jira_client,
        issue_client=issue_client,
        project_client=project_client,
        user_client=user_client,
        sprint_client=sprint_client,
        mongo=mongo,
        audit=audit,
        http=http_client,
    )

    register_resources(server, ctx)
    register_prompts(server, ctx)

    log.info(
        "app.created",
        transport=settings.mcp_transport,
        auth_mode=settings.jira_auth_mode,
        jira_base_url=str(settings.jira_base_url),
    )

    return ctx


__all__ = ["ServerContext", "create_app"]
