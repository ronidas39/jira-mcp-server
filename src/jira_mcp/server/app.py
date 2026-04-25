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
from ..auth.oauth import OAuthProvider
from ..auth.provider import AuthProvider
from ..clients.issues import IssueClient
from ..clients.jira import JiraClient, oauth_base_url
from ..clients.projects import ProjectClient
from ..clients.sprints import SprintClient
from ..clients.users import UserClient
from ..config.settings import Settings
from ..db.connection import MongoConnection
from ..db.repositories.audit import AuditRepository
from ..db.repositories.oauth_tokens import TokenRepository
from ..prompts import register as register_prompts
from ..resources import register as register_resources
from ..tools import register_all as register_all_tools
from ..tools.analytics import AnalyticsToolContext
from ..tools.issues import IssueToolContext
from ..tools.sprints import SprintToolContext
from ..utils.errors import AuthenticationError
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


def _build_api_token_provider(settings: Settings) -> AuthProvider:
    """Build the static-token auth provider from settings."""
    if settings.jira_email is None or settings.jira_api_token is None:
        msg = "api_token mode requires JIRA_EMAIL and JIRA_API_TOKEN"
        raise ValueError(msg)
    return ApiTokenAuth(settings.jira_email, settings.jira_api_token)


async def _pick_cloud_id(token_repo: TokenRepository) -> str:
    """Return the cloud_id from the single stored OAuth token record.

    The server is wired for one tenant per deployment, so the token store is
    expected to hold exactly one record. If it is empty, the operator must
    run the login script before starting the server; if it has more than
    one we fail loudly so a request never goes to the wrong tenant.
    """
    cursor = token_repo.coll.find({}, projection={"_id": 1})
    cloud_ids: list[str] = [doc["_id"] async for doc in cursor]
    if not cloud_ids:
        msg = (
            "oauth mode is enabled but no token is stored; "
            "run `python scripts/oauth_login.py` first."
        )
        raise AuthenticationError(msg)
    if len(cloud_ids) > 1:
        joined = ", ".join(cloud_ids)
        msg = (
            "oauth mode found multiple stored tenants; "
            f"clean up before starting. Candidates: {joined}"
        )
        raise AuthenticationError(msg)
    return cloud_ids[0]


async def resolve_oauth_cloud_id(settings: Settings) -> str:
    """Read the cloud_id of the single stored OAuth tenant.

    Called from the async entry point before ``create_app`` so the OAuth
    provider receives the cloud_id without ``create_app`` needing to be
    async itself. Raises with a clear pointer to the login script when no
    token is stored, since that is the most common operator error.

    Args:
        settings: Validated runtime configuration.

    Returns:
        The cloud_id of the single stored OAuth token record.

    Raises:
        AuthenticationError: When the token store is empty or contains more
            than one tenant.
    """
    mongo = MongoConnection(settings.mongo_uri, settings.mongo_db)
    try:
        repo = TokenRepository(mongo.db)
        return await _pick_cloud_id(repo)
    finally:
        await mongo.close()


def create_app(
    settings: Settings,
    *,
    oauth_cloud_id: str | None = None,
) -> ServerContext:
    """Compose runtime dependencies and return a frozen `ServerContext`.

    Args:
        settings: Validated runtime configuration.
        oauth_cloud_id: When OAuth is enabled the caller resolves the
            cloud_id asynchronously (via ``resolve_oauth_cloud_id``) and
            passes it in. Required when ``jira_auth_mode == "oauth"``;
            ignored otherwise.

    Returns:
        A `ServerContext` containing every long-lived dependency the server
        needs. Caller is responsible for invoking startup and shutdown
        hooks around the transport's serve loop.

    Raises:
        ValueError: When required settings for the chosen auth mode are
            missing, when oauth mode is selected without a cloud_id, or
            when two tool groups try to register the same name.
    """
    configure_logging(settings.log_level)
    log = get_logger("jira_mcp.server.app")

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_connections=settings.jira_max_concurrency),
    )

    mongo = MongoConnection(settings.mongo_uri, settings.mongo_db)
    audit = AuditRepository(mongo.db)

    auth_provider, jira_base_url = _build_auth_and_base_url(
        settings,
        http_client=http_client,
        mongo=mongo,
        oauth_cloud_id=oauth_cloud_id,
    )

    jira_client = JiraClient(
        base_url=jira_base_url,
        auth=auth_provider,
        http=http_client,
        max_retries=settings.jira_max_retries,
    )

    issue_client = IssueClient(jira_client)
    project_client = ProjectClient(jira_client)
    user_client = UserClient(jira_client)
    sprint_client = SprintClient(jira_client)

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
        jira_base_url=jira_base_url,
    )

    return ctx


def _build_auth_and_base_url(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient,
    mongo: MongoConnection,
    oauth_cloud_id: str | None,
) -> tuple[AuthProvider, str]:
    """Pick the auth provider and the matching Jira base URL.

    Kept as a separate helper so ``create_app`` stays readable: the choice
    of base URL depends on the auth mode (api_token uses the tenant's own
    ``*.atlassian.net``; oauth uses the ``api.atlassian.com/ex/jira/{id}``
    proxy) and tying the two together avoids a misconfiguration where the
    provider and the URL disagree about the tenant.
    """
    if settings.jira_auth_mode == "api_token":
        return _build_api_token_provider(settings), str(settings.jira_base_url)
    if settings.jira_auth_mode == "oauth":
        if oauth_cloud_id is None:
            msg = "oauth mode requires oauth_cloud_id; call resolve_oauth_cloud_id first."
            raise ValueError(msg)
        if (
            settings.jira_oauth_client_id is None
            or settings.jira_oauth_client_secret is None
            or settings.jira_oauth_redirect_uri is None
        ):
            msg = (
                "oauth mode requires JIRA_OAUTH_CLIENT_ID, "
                "JIRA_OAUTH_CLIENT_SECRET, and JIRA_OAUTH_REDIRECT_URI"
            )
            raise ValueError(msg)
        provider = OAuthProvider(
            client_id=settings.jira_oauth_client_id,
            client_secret=settings.jira_oauth_client_secret.get_secret_value(),
            redirect_uri=settings.jira_oauth_redirect_uri,
            scopes=settings.jira_oauth_scopes,
            token_repo=TokenRepository(mongo.db),
            http=http_client,
            cloud_id=oauth_cloud_id,
        )
        return provider, oauth_base_url(oauth_cloud_id)
    msg = f"unsupported jira_auth_mode: {settings.jira_auth_mode!r}"
    raise ValueError(msg)


__all__ = ["ServerContext", "create_app", "resolve_oauth_cloud_id"]
