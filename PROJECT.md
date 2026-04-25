# Project Charter: Jira MCP Server

## Scope

In scope for v1: an MCP server exposing Jira Cloud as tools, resources, and
prompts; a MongoDB-backed audit log and TTL cache; stdio and streamable-HTTP
transports; reference-quality documentation; a container image suitable for
local dev and remote hosting.

Out of scope for v1: Jira Server / Data Center, Confluence, Bitbucket
integration, multi-tenant deployment, custom UI or dashboard.

## Milestones

| ID | Milestone               | Description                                                           | Done when                                                       |
| -- | ----------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------- |
| M0 | Project bootstrap       | Skeleton, config, lint, test scaffolding                              | `pytest` passes, `mypy --strict` clean, smoke test green        |
| M1 | Jira client foundation  | Async HTTP client with auth, retries, rate-limit awareness            | Lists projects against a real Jira instance                     |
| M2 | MongoDB foundation      | Connection, repositories, audit log, TTL cache                        | Audit entries persist, cache TTL works, indexes ensured         |
| M3 | Read tools              | All FR-3xx, FR-4xx, FR-5xx read tools                                 | Each tool tested against fixtures                               |
| M4 | Write tools             | All FR-3xx write tools plus audit                                     | Bulk-create works end to end                                    |
| M5 | Sprint and analytics    | All FR-4xx plus FR-6xx                                                | Velocity report demoed                                          |
| M6 | Resources and prompts   | FR-7xx and FR-8xx                                                     | Templates work in MCP clients                                   |
| M7 | Hardening               | Rate limit polish, error polish, docs polish                          | All NFRs verified                                               |
| M8 | Release                 | Container image, examples, demo recording                             | v1.0.0 tag pushed                                               |

## Working agreements

1. Small steps. Land one milestone task at a time, run the quality gates after each.
2. Decisions that take more than thirty minutes to revisit get an architecture decision record before code is written.
3. Definition of done sits in `CONTRIBUTING.md` once that file lands; for now: tests pass, types pass, docstring on every public function, file under 400 lines, function under 50 lines.
4. Branching: trunk-based, feature branches under two days old.
5. Commit messages: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`).

## Risk register

| ID  | Risk                                       | Owner | Status                                  |
| --- | ------------------------------------------ | ----- | --------------------------------------- |
| R-1 | Jira API token expiry mid-session          | dev   | open: runbook required                  |
| R-2 | MCP spec drift                             | dev   | open: pin SDK version                   |
| R-3 | Custom field complexity in Jira            | dev   | open: generic id passthrough plus helper |
| R-4 | Mongo unavailable at runtime               | dev   | mitigated: disk buffer with replay      |
