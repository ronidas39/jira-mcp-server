# Detailed Design: Jira MCP Server

This document elaborates the module-level design. The high-level picture lives
in `../architecture/ARCHITECTURE.md`.

## 1. Server bootstrap (`src/jira_mcp/server/`)

### `app.py`

Single entry: `create_app(settings: Settings) -> Server`. It performs:

1. Initialise structured logging.
2. Build an `AuthProvider` from settings.
3. Build a `JiraClient` with the auth provider.
4. Build a `MongoConnection` and the repositories that sit on top of it.
5. Build the tool, resource, and prompt registries.
6. Register handlers with the MCP SDK Server.
7. Return the Server. The transport is applied separately so tests can drive it directly.

### `transport.py`

Wraps `stdio_server` and `streamable_http_server`. Selection by
`settings.mcp_transport`.

### `lifespan.py`

Startup runs connectivity checks (Jira ping, Mongo ping). Shutdown flushes the
audit buffer and closes clients.

## 2. Jira client (`src/jira_mcp/clients/jira.py`)

```python
class JiraClient:
    def __init__(self, base_url: str, auth: AuthProvider, http: httpx.AsyncClient): ...
    async def request(self, method: str, path: str, *, json=None, params=None) -> dict: ...
    async def get(self, path: str, **kw) -> dict: ...
    async def post(self, path: str, **kw) -> dict: ...
    # put, delete follow the same shape
```

The client always sends `Accept: application/json`. The auth header is injected
by the `AuthProvider`. 429 and 5xx responses are retried with exponential
backoff via `utils/retry.py`. Every request is logged with a correlation ID;
neither the request body nor the auth header is logged.

### Higher-level helpers

`clients/jira.py` stays generic. Domain methods live in:

- `clients/issues.py`: issue CRUD, search, transitions
- `clients/sprints.py`: agile and board endpoints
- `clients/projects.py`: project and metadata
- `clients/users.py`: user search and resolution

Each accepts a `JiraClient` and returns Pydantic models.

## 3. Auth (`src/jira_mcp/auth/`)

### `provider.py`

```python
class AuthProvider(Protocol):
    async def headers(self) -> dict[str, str]: ...
    async def refresh(self) -> None: ...  # no-op for static tokens
```

### `api_token.py`

Basic auth: `Authorization: Basic base64(email:token)`.

### `oauth.py`

3LO OAuth flow. Tokens persist in MongoDB `oauth_tokens`. The provider
refreshes on a 401 and retries once.

Selection happens via `settings.jira_auth_mode` (`api_token` or `oauth`).

## 4. Tool pattern

Every tool follows this shape:

```python
# src/jira_mcp/tools/issues.py
from pydantic import BaseModel, Field

class SearchIssuesInput(BaseModel):
    jql: str = Field(..., description="JQL query string")
    max_results: int = Field(50, ge=1, le=100)
    fields: list[str] | None = None

class SearchIssuesOutput(BaseModel):
    total: int
    issues: list[IssueSummary]

@tool(name="search_issues", description="Search Jira issues using JQL...")
async def search_issues(
    input: SearchIssuesInput,
    ctx: ToolContext,
) -> SearchIssuesOutput:
    """Search Jira issues using JQL. Use when the user asks to find issues
    matching criteria. Prefer this over get_issue when the key is unknown."""
    return await ctx.jira_issues.search(...)
```

Tool descriptions are written for the model. State when to use the tool, when
not to use it, and what shape to expect back.

## 5. Resource pattern

```python
@resource_handler("jira://issue/{key}")
async def get_issue_resource(key: str, ctx: ResourceContext) -> Resource:
    issue = await ctx.jira_issues.get(key)
    return Resource(
        uri=f"jira://issue/{key}",
        name=f"{key}: {issue.summary}",
        mime_type="application/json",
        content=issue.model_dump_json(),
    )
```

## 6. MongoDB schema

### `audit_log` (immutable, append-only)

```json
{
  "_id": "ObjectId",
  "ts": "ISODate",
  "tool": "create_issue",
  "input_hash": "sha256:...",
  "input_summary": { "project_key": "PROJ", "summary": "..." },
  "response_status": "success",
  "jira_id": "PROJ-123",
  "actor": "user@example.com",
  "duration_ms": 412,
  "correlation_id": "uuid"
}
```

Indexes: `{ts: -1}`, `{tool: 1, ts: -1}`, `{actor: 1, ts: -1}`.

### `cache` (TTL)

```json
{
  "_id": "issue:PROJ-123",
  "data": { },
  "expires_at": "ISODate"
}
```

TTL index on `expires_at` with `expireAfterSeconds=0`.

### `oauth_tokens` (only when OAuth is enabled)

```json
{
  "_id": "<account_id>",
  "access_token": "<encrypted>",
  "refresh_token": "<encrypted>",
  "expires_at": "ISODate"
}
```

## 7. Error hierarchy

```python
class JiraMcpError(Exception): ...
class ConfigurationError(JiraMcpError): ...
class AuthenticationError(JiraMcpError): ...
class JiraApiError(JiraMcpError):
    status: int
    body: dict
class RateLimitError(JiraApiError): ...
class UpstreamError(JiraApiError): ...
class NotFoundError(JiraApiError): ...
class ValidationError(JiraMcpError): ...
class PersistenceError(JiraMcpError): ...
```

Tools translate these into structured MCP error responses. The dispatcher's
outer handler catches anything else and returns a generic `InternalError` with
a correlation ID; stack traces never reach the model.

## 8. Logging

`structlog` is configured at app start. Default keys on every record:
`correlation_id`, `tool` (when in tool context), `level`, `event`, `ts`.
Sensitive keys (`Authorization`, `password`, `token`, `api_key`, `secret`) are
replaced with `***` in a processor before rendering.

## 9. Testing strategy

- **Unit**: each tool is tested with a mocked `JiraClient`. Fixtures live in `tests/fixtures/jira/`.
- **Integration**: `tests/integration/` runs against a real Jira sandbox. Skipped unless `RUN_INTEGRATION=1`.
- **Contract**: schema snapshots of MCP tool definitions catch accidental breaking changes.

## 10. Open design questions

Tracked here until resolved, then promoted to architecture decisions:

- Should the Jira changelog be a resource or a tool?
- Cache invalidation policy on writes: invalidate a single key or scan and purge by prefix?
- Custom field naming: expose raw IDs (`customfield_10001`) or auto-resolve to readable names?
