# Architecture: Jira MCP Server

## 1. System context (C4)

```
+------------------+     stdio     +-------------------+    HTTPS    +-------------------+
|   MCP client     |<------------->|  Jira MCP Server  |<----------->| Jira Cloud REST   |
| (Claude Desktop, |     HTTP      |  (this project)   |             |       API v3      |
|  Cursor, others) |               |                   |             +-------------------+
+------------------+               |                   |
                                   |                   |             +-------------------+
                                   |                   |    TCP      |     MongoDB       |
                                   |                   |<----------->| (audit, cache)    |
                                   +-------------------+             +-------------------+
```

## 2. Container view

The server runs as a single Python process. Inside it:

```
+----------------------------------------------------------------------+
|                          Jira MCP Server                              |
|                                                                      |
|   +-----------+   +-----------+   +-----------+                       |
|   | Transport |-->|  Server   |-->|  Tools    |                       |
|   | stdio /   |   | (MCP SDK  |   | Registry  |                       |
|   | http      |   |  wiring)  |   |           |                       |
|   +-----------+   +-----------+   +-----------+                       |
|                                          |                            |
|                          +---------------+----------------+            |
|                          v               v                v            |
|                     +---------+    +----------+     +---------+         |
|                     |  Issue  |    |  Sprint  |     |Analytics|         |
|                     |  Tools  |    |  Tools   |     |  Tools  |         |
|                     +----+----+    +----+-----+     +----+----+         |
|                          |              |                |              |
|                          +------+-------+----------------+              |
|                                 v                                       |
|                          +--------------+                               |
|                          | Jira client  | (auth, retries, ADF, rate limits) |
|                          +-------+------+                               |
|                                  v                                       |
|                          +--------------+                               |
|                          |  httpx async |                               |
|                          +--------------+                               |
|                                                                         |
|   +------------+    +-------------+    +-------------+                  |
|   | Resources  |    |   Prompts   |    |   Audit     |                  |
|   | Registry   |    |  Registry   |    | Repository  |                  |
|   +------------+    +-------------+    +------+------+                  |
|                                               v                          |
|                                        +-------------+                   |
|                                        | Motor (Mongo)|                  |
|                                        +-------------+                   |
+----------------------------------------------------------------------+
```

## 3. Module responsibilities

| Module       | Responsibility                                                                                  |
| ------------ | ----------------------------------------------------------------------------------------------- |
| `server/`    | Bootstrap, transport selection, startup and shutdown hooks, wiring of tools, resources, prompts |
| `tools/`     | One file per tool group; each tool is an async function with a Pydantic input schema            |
| `resources/` | URI handlers for `jira://` resource fetches                                                     |
| `prompts/`   | Prompt template registrations                                                                   |
| `clients/`   | `JiraClient` async wrapper over httpx; auth headers, retries, rate-limit backoff, ADF helpers   |
| `auth/`      | API token and OAuth flows behind a single `AuthProvider` Protocol                                |
| `db/`        | Motor connection, repositories (`AuditRepository`, `CacheRepository`), TTL indexes              |
| `models/`    | Pydantic models for Jira entities (Issue, Sprint, Project, User) and tool I/O                   |
| `utils/`     | `errors.py`, `logging.py`, `retry.py`, `jql.py`                                                 |

## 4. Request flow for a tool call

1. The MCP client issues `tools/call` with a name and arguments.
2. The transport layer parses JSON-RPC and hands the request to the SDK dispatcher.
3. The SDK invokes the registered tool function.
4. The tool function:
   1. Validates input via Pydantic.
   2. Calls the relevant `JiraClient` helper.
   3. The client adds auth, performs the request via httpx, retries on 429 and 5xx with backoff.
   4. The response is validated and mapped to a Pydantic output model.
   5. If this was a write, `AuditRepository.record(...)` is called.
5. The tool returns the Pydantic model and the SDK serialises it to a JSON-RPC response.
6. The transport ships the response back to the client.

## 5. Persistence flow

```
Write tool ---> Jira API (success) ---> AuditRepository.insert ---> mongo.audit_log
                                    \-> optional cache invalidation

Read tool  ---> CacheRepository.get(key) ---> hit  ---> return cached
                                          \-> miss ---> JiraClient.fetch ---> CacheRepository.set(key, ttl)
```

## 6. Failure modes

| Failure          | Detection                       | Response                                                                                |
| ---------------- | ------------------------------- | --------------------------------------------------------------------------------------- |
| Jira 401         | client checks status            | `AuthenticationError` raised; tool returns a structured error to the model              |
| Jira 429         | client retry layer              | exponential backoff up to three retries; then `RateLimitError`                          |
| Jira 5xx         | client retry layer              | same retry policy; surfaces as `UpstreamError`                                          |
| Mongo down       | repository exception            | buffer to local disk (`.audit-buffer.jsonl`); flush on reconnect                        |
| Validation error | Pydantic                        | `ValidationError` with field-level details                                              |
| Unknown          | dispatcher's outer handler      | log full trace, return generic `InternalError`; never leak a stack to the model         |

## 7. Concurrency model

A single asyncio event loop. Every Jira and Mongo I/O call is async. CPU-bound
work (for example, a future JQL parser) is wrapped in `run_in_executor` if it
runs longer than ten milliseconds. There is no global mutable state outside the
registries, which are write-once during startup.

## 8. Configuration

All configuration lives in `.env` and is loaded by `config/settings.py` using
`pydantic-settings`. See `.env.example` for the full template. Settings are
immutable after startup.

## 9. Deployment

- Local development: `python -m jira_mcp` with a populated `.env`.
- Container: `docker compose up` brings up MongoDB and the server together.
- Remote: streamable HTTP transport behind a TLS-terminating reverse proxy.

## 10. Future extensions

A pluggable persistence backend (Postgres or Neo4j behind the same repository
interface). A Confluence MCP server reusing the `clients/` shape. A webhook
listener mode for Jira push notifications. OpenTelemetry tracing.
