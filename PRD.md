# Product Requirements Document: Jira MCP Server

## 1. Vision

Give any MCP-compatible client (Claude Desktop, Cursor, Windsurf, custom agents)
typed access to Atlassian Jira Cloud, so engineers, leads, and project managers
can drive Jira from natural language without leaving their tool of choice.

## 2. Problem

When a developer or PM is working with an assistant and wants to triage a bug,
pull sprint status, generate issues from a meeting transcript, update workflow
states, or analyse team workload, they have to switch out of the conversation,
hunt through Jira's UI, do the work by hand, and switch back. The cost is
context switches and copy-paste mistakes. We can remove both.

## 3. Target users

| Persona               | Need                                                                      |
| --------------------- | ------------------------------------------------------------------------- |
| Developer             | Issue context while coding; create bugs from stack traces; status updates without breaking flow |
| Tech lead / EM        | Sprint reviews, workload analysis, backlog grooming via natural language  |
| Project manager       | Bulk issue creation from notes, cross-project status reports              |
| Autonomous agent      | Programmatic Jira access with stable schemas and an audit trail           |

## 4. Goals

1. Cover the eighty percent of Jira operations that drive day to day PM and dev work.
2. Be runnable in under five minutes from a fresh clone.
3. Zero secrets in code; production-safe defaults.
4. Persistent, queryable audit trail of every write.
5. Read as a reference implementation that other MCP servers can copy.

## 5. Non-goals (v1)

- Jira Server / Data Center. Cloud only for v1; the client layer is abstracted so a future driver is feasible.
- Confluence integration. Different REST surface, separate server.
- Bitbucket integration. Same reasoning.
- Custom Jira app marketplace listing.
- Webhook ingestion. The server is request/response in v1; a webhook listener is v2 territory.

## 6. Functional scope

### 6.1 Issue management

Search by JQL; get an issue by key with comments, attachments, and transitions;
create an issue with custom fields; update any editable field; transition an
issue through workflow; bulk-create from a structured input; comment add, edit,
delete; link issues with the standard relations (blocks, relates, duplicates).

### 6.2 Sprint and board

List boards. List sprints for a board with state filter. Get sprint details and
its issues. Move issues into a sprint. Sprint progress report covering
committed vs done with a simple burndown summary.

### 6.3 Project and metadata

List projects. Project details including issue types, workflows, and custom
fields. User search with permission filter. Resolve a user by email or display
name. List transitions for an issue. List custom fields with id to name mapping.

### 6.4 Analytics

Workload by assignee (count and story-point totals). Issues by status across a
project. Velocity over the last N sprints. Stale issues, defined as no update
in N days.

### 6.5 MCP surface

Tools for everything in 6.1 to 6.4. Resources at `jira://issue/{key}`,
`jira://sprint/{id}`, and `jira://project/{key}` for read-only context
injection. Prompts for `/sprint-review`, `/backlog-grooming`, `/triage-bugs`,
and `/standup-summary`.

## 7. Non-functional requirements

| ID     | Requirement |
| ------ | ----------- |
| NFR-1  | All Jira calls complete in p95 under 3s under nominal load |
| NFR-2  | Server respects Jira rate limits with exponential backoff on 429 |
| NFR-3  | Every write is audited with timestamp, tool name, input hash, response status, and actor |
| NFR-4  | No credentials in code, logs, or tool responses |
| NFR-5  | `mypy --strict` and `ruff check` pass on every commit |
| NFR-6  | Test coverage at or above eighty percent on tools/ and clients/ |
| NFR-7  | Cold-start under 2s |
| NFR-8  | Container image under 200MB |
| NFR-9  | Logs are structured JSON, parseable by Datadog, ELK, or CloudWatch |
| NFR-10 | New developer can ship a tool inside their first day |

## 8. Constraints

Python 3.11+. MongoDB 6.0+. Jira Cloud REST API v3. The MCP specification at
its current stable revision.

## 9. Success metrics

Time to first tool call from a fresh clone under five minutes. All v1
functional requirements implemented and tested. End-to-end demo of "create a
sprint plan from meeting notes" running under sixty seconds. The codebase
serves as a template for a future Confluence or ServiceNow MCP server.

## 10. Phasing

| Phase | Scope                                                | Exit criteria                                        |
| ----- | ---------------------------------------------------- | ---------------------------------------------------- |
| P0    | Project skeleton, config, logging, Mongo, Jira client | Server starts, connects to Jira, lists projects     |
| P1    | Read tools                                           | Search, get issue, list sprints, list projects shipped |
| P2    | Write tools                                          | Create, update, transition, comment shipped and audited |
| P3    | Resources and prompts                                | Templates usable from MCP clients                    |
| P4    | Analytics                                            | Workload, velocity, stale-issue reports              |
| P5    | Hardening                                            | Rate limit polish, error polish, docs polish, container |

## 11. Risks and mitigations

| Risk                                  | Mitigation                                                          |
| ------------------------------------- | ------------------------------------------------------------------- |
| Jira API token expiry mid-session     | Detect 401, surface clear error to the model, document rotation in a runbook |
| Jira rate limiting under heavy use    | Built-in retry plus backoff; cache hot reads in MongoDB             |
| MCP spec changes                      | Pin SDK version; change goes through an architecture decision       |
| Custom field complexity               | Generic field_id passthrough plus a helper resolver                  |
| Mongo unavailable at runtime          | Audit writes buffer to disk and flush on reconnect                   |
