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
