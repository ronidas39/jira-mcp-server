# Use Cases: Jira MCP Server

Each use case is tied to functional requirement IDs from `REQUIREMENTS.md`. They
describe the scenarios the server must handle end to end.

## UC-01 Find all open bugs in a project

- **Actor**: developer
- **Trigger**: "find all open bugs in PROJ assigned to me"
- **Flow**:
  1. The client invokes `search_issues` with a JQL such as `project = PROJ AND issuetype = Bug AND status != Done AND assignee = currentUser()`.
  2. The server returns matching issues with the projected fields.
- **Requirements**: FR-301
- **Success**: results in p95 under three seconds

## UC-02 Create a bug from a stack trace

- **Actor**: developer
- **Trigger**: user pastes a stack trace and asks to file it as a bug in PROJ
- **Flow**:
  1. The assistant summarises the trace into a title plus description (markdown to ADF conversion happens server side).
  2. The client calls `create_issue(project_key=PROJ, issue_type=Bug, summary, description)`.
  3. The server creates the issue and writes an audit entry.
  4. The server returns the issue key and URL.
- **Requirements**: FR-303, FR-901
- **Success**: issue exists in Jira; audit entry exists in MongoDB

## UC-03 Bulk-create issues from meeting notes

- **Actor**: project manager
- **Trigger**: PM pastes notes and asks to create issues for each action item
- **Flow**:
  1. The assistant parses notes into a structured list of `{summary, description, assignee_email}`.
  2. The client invokes `bulk_create_issues` with up to fifty items.
  3. The server resolves assignee emails to accountIds via `resolve_user`.
  4. The server creates issues sequentially with a concurrency cap and audit-logs each one.
  5. The response lists the created keys and any failures.
- **Requirements**: FR-306, FR-504, FR-901
- **Success**: every valid item is created, and any failure is reported clearly

## UC-04 Sprint status review

- **Actor**: tech lead
- **Trigger**: "give me the status of the current sprint for board 42"
- **Flow**:
  1. The client invokes `list_sprints(board_id=42, state="active")`.
  2. The client invokes `sprint_report(sprint_id=...)`.
  3. The server returns committed vs done, scope changes, and items at risk.
- **Requirements**: FR-402, FR-405
- **Success**: a tech lead can run a sprint review meeting from this output alone

## UC-05 Workload analysis before planning

- **Actor**: engineering manager
- **Trigger**: "show me the workload for the team in PROJ"
- **Flow**:
  1. The client invokes `workload_by_assignee(project_key="PROJ")`.
  2. The server returns per-assignee issue count and story-point totals.
- **Requirements**: FR-601
- **Success**: overloaded engineers are visible in seconds

## UC-06 Workflow transition with comment

- **Actor**: developer
- **Trigger**: "move PROJ-123 to In Review with a comment that the PR is ready"
- **Flow**:
  1. The client calls `list_transitions(PROJ-123)` to find the right id.
  2. The client calls `transition_issue(PROJ-123, transition_id=..., comment="PR ready: <url>")`.
  3. The server transitions, adds the comment, and writes an audit entry.
- **Requirements**: FR-305, FR-505, FR-901
- **Success**: issue is in the new state and the comment is visible

## UC-07 Stale-issue cleanup

- **Actor**: project manager
- **Trigger**: "find issues in PROJ that haven't been updated in thirty days"
- **Flow**:
  1. The client calls `stale_issues(project_key="PROJ", days=30)`.
  2. The PM reviews the list and asks for a `stale-pending-review` label on each.
  3. The client calls `update_issue` per item.
- **Requirements**: FR-604, FR-304, FR-901
- **Success**: stale issues are tagged for cleanup

## UC-08 Resource injection into a coding session

- **Actor**: developer using an MCP-capable IDE assistant
- **Trigger**: "look at PROJ-456 and propose a fix"
- **Flow**:
  1. The client reads the `jira://issue/PROJ-456` resource.
  2. Issue context (title, description, comments, recent changelog) is injected into the model context.
  3. The assistant proposes code changes grounded in the full context.
- **Requirements**: FR-701
- **Success**: the developer gets contextual suggestions without copy-pasting issue text

## UC-09 Sprint-review prompt template

- **Actor**: tech lead
- **Trigger**: user runs `/sprint-review`
- **Flow**:
  1. The prompt asks which sprint to review.
  2. It calls `sprint_report` and `workload_by_assignee` as tools.
  3. It returns a markdown retrospective draft.
- **Requirements**: FR-801
- **Success**: a draft retrospective in under thirty seconds

## UC-10 Auth rotation

- **Actor**: operator
- **Trigger**: API token nearing expiry
- **Flow**:
  1. The operator generates a new token at id.atlassian.com.
  2. The operator updates `JIRA_API_TOKEN` in the deployment.
  3. The operator restarts the server.
  4. Startup connectivity check confirms the new token works.
- **Requirements**: FR-103, FR-104, NFR-301
- **Success**: no production downtime; rotation runbook followed
