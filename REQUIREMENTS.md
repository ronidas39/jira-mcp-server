# Requirements: Jira MCP Server

This document is the canonical, traceable list of requirements. Every
requirement carries a stable ID. Tests reference these IDs in their docstrings.
Architecture decisions reference them in their context section.

## Functional requirements

### FR-100 Server lifecycle

- **FR-101** Server starts via `python -m jira_mcp` with stdio transport.
- **FR-102** Server optionally starts with streamable HTTP transport when `MCP_TRANSPORT=http`.
- **FR-103** Server validates required environment variables at startup and fails fast with a human readable error if any are missing.
- **FR-104** Server verifies Jira connectivity (one ping call) at startup; logs success or fails with a clear error.
- **FR-105** Server verifies MongoDB connectivity at startup.

### FR-200 Authentication

- **FR-201** Server supports Jira Cloud API token plus email basic auth.
- **FR-202** Server supports Jira Cloud OAuth 2.0 (3LO) as an alternative auth mode (gated by `JIRA_AUTH_MODE`).
- **FR-203** Credentials are read only from environment variables (loaded from `.env` locally).
- **FR-204** Credentials never appear in logs, error messages, or tool responses.

### FR-300 Issue tools

- **FR-301** `search_issues(jql, max_results, fields)`: JQL search with field projection.
- **FR-302** `get_issue(key, expand)`: full issue details, optional expansions for comments, transitions, changelog.
- **FR-303** `create_issue(project_key, summary, issue_type, description, fields)`: create with arbitrary fields.
- **FR-304** `update_issue(key, fields)`: partial update.
- **FR-305** `transition_issue(key, transition_id_or_name, comment?)`: workflow change.
- **FR-306** `bulk_create_issues(issues[])`: create up to fifty issues in one call.
- **FR-307** `add_comment(key, body)`: append a comment.
- **FR-308** `link_issues(from_key, to_key, link_type)`: create an issue link.
- **FR-309** `delete_issue(key)`: gated by `ALLOW_DELETE_ISSUES=true`; off by default.

### FR-400 Sprint and board tools

- **FR-401** `list_boards(project_key?)`: list scrum and kanban boards.
- **FR-402** `list_sprints(board_id, state?)`: list sprints with state filter.
- **FR-403** `get_sprint(sprint_id)`: sprint details and issue list.
- **FR-404** `move_to_sprint(issue_keys[], sprint_id)`: bulk move.
- **FR-405** `sprint_report(sprint_id)`: committed vs done, scope changes, burndown summary.

### FR-500 Project and metadata tools

- **FR-501** `list_projects()`: every accessible project.
- **FR-502** `get_project(key)`: issue types, workflows, custom fields.
- **FR-503** `list_users(query?, project_key?)`: search users.
- **FR-504** `resolve_user(email_or_displayname)`: get accountId.
- **FR-505** `list_transitions(issue_key)`: available workflow transitions.
- **FR-506** `list_custom_fields()`: id to name map for custom fields.

### FR-600 Analytics tools

- **FR-601** `workload_by_assignee(project_key, status_filter?)`: issue count plus story points per assignee.
- **FR-602** `issues_by_status(project_key, group_by?)`: status histogram.
- **FR-603** `velocity(board_id, last_n_sprints)`: committed vs delivered story points.
- **FR-604** `stale_issues(project_key, days)`: issues not updated in N days.

### FR-700 Resources (MCP read-only URIs)

- **FR-701** `jira://issue/{key}`: full issue as resource.
- **FR-702** `jira://sprint/{id}`: sprint snapshot.
- **FR-703** `jira://project/{key}`: project metadata.
- **FR-704** `jira://search?jql=...`: JQL result set.

### FR-800 Prompts

- **FR-801** `/sprint-review`: guided sprint retrospective prompt.
- **FR-802** `/backlog-grooming`: backlog cleanup walkthrough.
- **FR-803** `/triage-bugs`: bug triage with priority recommendations.
- **FR-804** `/standup-summary`: daily standup digest from issue activity.

### FR-900 Persistence and audit

- **FR-901** Every write tool call inserts a record into the MongoDB `audit_log` collection.
- **FR-902** Audit record fields: `ts`, `tool`, `input_hash`, `input_summary`, `response_status`, `jira_id`, `actor`, `duration_ms`, `correlation_id`.
- **FR-903** Hot reads (issue details, project metadata) may be cached in MongoDB with a TTL.

## Non-functional requirements

### NFR-100 Performance

- **NFR-101** p95 tool latency under 3s assuming nominal Jira response time.
- **NFR-102** Cold-start under 2s.
- **NFR-103** Memory footprint at idle under 150MB.

### NFR-200 Reliability

- **NFR-201** Retry on Jira 429 and 5xx with exponential backoff (max three retries).
- **NFR-202** Graceful degradation when MongoDB is down: tools still work and the audit log buffers to disk.
- **NFR-203** No unhandled exceptions reach the MCP transport layer.

### NFR-300 Security

- **NFR-301** No secrets in code or version control. `.env` is gitignored.
- **NFR-302** Reject `http://` Jira URLs at startup (HTTPS only).
- **NFR-303** Audit log entries are immutable: no update or delete operations on `audit_log`.
- **NFR-304** Every write tool logs the actor identity resolved from the auth context.

### NFR-400 Observability

- **NFR-401** Logs are structured JSON via `structlog`.
- **NFR-402** Every request gets a correlation ID.
- **NFR-403** Tool execution time and outcome are recorded for every call.

### NFR-500 Maintainability

- **NFR-501** `mypy --strict` passes.
- **NFR-502** `ruff check` and `ruff format` pass.
- **NFR-503** Test coverage at or above eighty percent on `tools/` and `clients/`.
- **NFR-504** No file over 400 lines, no function over 50 lines (enforced by linter where possible).
- **NFR-505** Every public function has a docstring.

### NFR-600 Compatibility

- **NFR-601** Supports the MCP specification at its current stable revision.
- **NFR-602** Tested against major MCP clients that support stdio transports.
- **NFR-603** Container image runs on linux/amd64 and linux/arm64.

## Traceability

Each test in `tests/` references one or more requirement IDs in its docstring.
