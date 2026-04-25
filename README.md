# Jira MCP Server

A Model Context Protocol server for Atlassian Jira Cloud. It exposes the operations
you actually run during the day, issue CRUD, JQL search, sprints, projects, workflow
transitions, comments, and a small analytics surface, as MCP tools, resources, and
prompt templates so any MCP-compatible client can drive Jira from natural language.

## Why this exists

Most teams already live in Jira. The friction is the click path: switch out of the
editor, hunt for the issue, change the field, write the comment, switch back. For
agents and assistants the friction is worse, because they cannot click. This server
gives them a typed, audited interface to do the same work, with structured logging,
retries on Jira rate limits, and an immutable audit trail in MongoDB.

## Quick start

```bash
git clone https://github.com/ronidas39/jira-mcp-server.git
cd jira-mcp-server
pip install -e ".[dev]"
cp .env.example .env
# fill in JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, MONGO_URI
python -m jira_mcp
```

Python 3.11 or newer is required. Atlassian API tokens are created at
https://id.atlassian.com/manage-profile/security/api-tokens.

For a local MongoDB:

```bash
docker compose up -d mongodb
python scripts/init_db.py   # creates the jira_mcp database with indexes
```

### Running with OAuth

The server supports Atlassian's three-legged OAuth (3LO) as an alternative to
API tokens. Use it when the deployment must act on behalf of a real user
account, or when an API token is not an option for the team.

1. Create an OAuth 2.0 (3LO) app at
   https://developer.atlassian.com/console/myapps/. Add the Jira REST API
   permissions you need (the defaults below cover the tools shipped here).
2. Register a redirect URI that points at a port on your machine. The login
   script will bind a short-lived listener to that port. A typical value is
   `http://localhost:9000/callback`.
3. Set the OAuth fields in `.env`:

   ```
   JIRA_AUTH_MODE=oauth
   JIRA_OAUTH_CLIENT_ID=...
   JIRA_OAUTH_CLIENT_SECRET=...
   JIRA_OAUTH_REDIRECT_URI=http://localhost:9000/callback
   JIRA_OAUTH_SCOPES=read:jira-work write:jira-work read:jira-user offline_access
   ```

   `offline_access` must stay in the scope list so Atlassian issues a refresh
   token. Without it the server cannot stay logged in across restarts.

4. Run the one-shot login script:

   ```bash
   python scripts/oauth_login.py
   ```

   The script opens the consent screen in your browser, captures the
   redirect, exchanges the code, resolves the tenant's `cloud_id`, and writes
   the tokens to MongoDB. On success it prints `ok cloud_id=<id>`.

5. Start the server as usual:

   ```bash
   python -m jira_mcp
   ```

   In OAuth mode, REST calls go through `https://api.atlassian.com/ex/jira/{cloudId}`
   rather than your tenant's `*.atlassian.net` host. The provider refreshes the
   access token automatically when it is within sixty seconds of expiry. If the
   refresh token itself is rejected (revoked, rotated, or expired) the server
   raises a clear authentication error pointing back at `scripts/oauth_login.py`.

### Running over HTTP

The default transport is stdio. For browser UIs or remote clients, run the
streamable HTTP transport instead:

```bash
MCP_TRANSPORT=http MCP_HTTP_PORT=8765 python -m jira_mcp
```

The server mounts the MCP endpoint at `/mcp`. Override `MCP_CORS_ORIGINS`
(comma-separated) to allow a non-default UI origin. Smoke-test the endpoint
with an `initialize` request:

```bash
curl -i -X POST http://127.0.0.1:8765/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

The response carries an `Mcp-Session-Id` header; reuse it on later
requests to keep the same session.

## Connecting from a client

Claude Desktop expects an entry under `mcpServers` in `claude_desktop_config.json`.
A working sample sits at `examples/claude_desktop_config.json`. Cursor's wiring is
in `examples/cursor_mcp.json`. Any MCP-compatible client that can spawn a stdio
process will work the same way.

For remote deployments, set `MCP_TRANSPORT=http` and put the server behind a
TLS-terminating reverse proxy. The HTTP transport implements the streamable-http
profile from the MCP specification.

## Layout

```
src/jira_mcp/
  server/        MCP server bootstrap, transport selection, lifespan hooks
  tools/         One module per tool group: issues, sprints, projects, analytics
  resources/     URI handlers for jira://issue, jira://sprint, jira://project
  prompts/       Prompt templates exposed as slash commands
  clients/       Async Jira HTTP wrapper plus per-domain helpers
  auth/          API token and OAuth providers behind a single Protocol
  db/            Motor connection plus repositories (audit, cache)
  models/        Pydantic models for Jira entities and tool I/O
  utils/         Logging, error hierarchy, retries, JQL helpers
```

Hard rules: every Jira and Mongo call is async, every tool boundary uses Pydantic,
every public function has a docstring, no file goes past 400 lines, no function
past 50.

## Tests and quality gates

```bash
ruff check src tests
ruff format --check src tests
mypy src
pytest
```

Integration tests under `tests/integration/` are skipped unless
`RUN_INTEGRATION=1` is set, because they hit a real Jira sandbox.

## Documentation

- `PRD.md` for scope and goals
- `REQUIREMENTS.md` for functional and non-functional requirements with stable IDs
- `PROJECT.md` for milestones and working agreements
- `docs/architecture/ARCHITECTURE.md` for the system design and data flow
- `docs/design/DESIGN.md` for module-level design
- `docs/use-cases/USE_CASES.md` for the scenarios the server is built to handle
- `docs/api/TOOLS.md` for the MCP tool reference
- `docs/runbooks/setup-jira-credentials.md` for credential setup and rotation

## License

MIT. See `LICENSE` once added.
