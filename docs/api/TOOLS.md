# API Reference: MCP Tools

This is the public surface of the server. Tool entries follow a single shape so
the model and humans can scan them quickly.

## Convention

```
### tool_name
Purpose: when the model should call this
Input (Pydantic):
  field: type, description
Output (Pydantic):
  field: type, description
Errors: AuthenticationError, NotFoundError, ValidationError, UpstreamError
Audit: yes / no
Requirement: FR-XXX
```

## Issue tools

### search_issues

- **Purpose**: search Jira issues using JQL. Use this when the user asks to find issues matching criteria. Prefer over `get_issue` when the key is unknown.
- **Input**: `jql: str`, `max_results: int = 50` (1 to 100), `fields: list[str] | None`
- **Output**: `total: int`, `issues: list[IssueSummary]`
- **Errors**: ValidationError (bad JQL), UpstreamError
- **Audit**: no (read-only)
- **Requirement**: FR-301

### get_issue

- **Purpose**: fetch a single issue by key with optional expansions. Use when the issue key is already known.
- **Input**: `key: str` (for example `PROJ-123`), `expand: list[str] | None` (comments, transitions, changelog).
- **Output**: full `Issue`
- **Audit**: no
- **Requirement**: FR-302

### create_issue

- **Purpose**: create a new issue. Use when the user describes a bug, story, or task to file.
- **Input**: project_key, summary, issue_type, description, fields
- **Output**: `key: str`, `url: str`, `id: str`
- **Audit**: yes
- **Requirement**: FR-303

### update_issue

- **Purpose**: partial update of an issue. Use to change status fields, add labels, edit summary, and similar.
- **Input**: key, fields (dict)
- **Output**: `key: str`, `updated_fields: list[str]`
- **Audit**: yes
- **Requirement**: FR-304

### transition_issue

- **Purpose**: move an issue through workflow. Always call `list_transitions` first if the user gives a state name rather than an id.
- **Input**: key, transition_id_or_name, optional comment
- **Output**: `key: str`, `from_status: str`, `to_status: str`
- **Audit**: yes
- **Requirement**: FR-305

### bulk_create_issues

- **Purpose**: create up to fifty issues in one call. Use after parsing meeting notes or lists.
- **Input**: list of `{project_key, summary, issue_type, description, fields}`
- **Output**: `created: list[CreatedIssue]`, `failed: list[BulkCreateFailure]`
- **Audit**: yes (one entry per issue)
- **Requirement**: FR-306

### add_comment

- **Purpose**: add a comment to an issue. Markdown is converted to ADF.
- **Input**: key, body
- **Output**: `comment_id: str`
- **Audit**: yes
- **Requirement**: FR-307

### link_issues

- **Purpose**: link two issues. Common link types: `Blocks`, `Relates`, `Duplicate`.
- **Input**: from_key, to_key, link_type
- **Output**: `link_id: str`
- **Audit**: yes
- **Requirement**: FR-308

### delete_issue

- **Purpose**: delete an issue. Disabled by default; gated by `ALLOW_DELETE_ISSUES=true`.
- **Input**: key
- **Output**: `deleted: bool`
- **Audit**: yes
- **Requirement**: FR-309

## Sprint and board tools

- `list_boards` (FR-401)
- `list_sprints` (FR-402)
- `get_sprint` (FR-403)
- `move_to_sprint` (FR-404)
- `sprint_report` (FR-405)

## Project and metadata tools

- `list_projects` (FR-501)
- `get_project` (FR-502)
- `list_users` (FR-503)
- `resolve_user` (FR-504)
- `list_transitions` (FR-505)
- `list_custom_fields` (FR-506)

## Analytics tools

- `workload_by_assignee` (FR-601)
- `issues_by_status` (FR-602)
- `velocity` (FR-603)
- `stale_issues` (FR-604)

## Resources

| URI                       | Description           | Requirement |
| ------------------------- | --------------------- | ----------- |
| `jira://issue/{key}`      | full issue            | FR-701      |
| `jira://sprint/{id}`      | sprint snapshot       | FR-702      |
| `jira://project/{key}`    | project metadata      | FR-703      |
| `jira://search?jql=...`   | JQL result set        | FR-704      |

## Prompts

| Slash               | Purpose                          | Requirement |
| ------------------- | -------------------------------- | ----------- |
| `/sprint-review`    | guided retrospective             | FR-801      |
| `/backlog-grooming` | backlog cleanup walkthrough      | FR-802      |
| `/triage-bugs`      | bug triage with priority         | FR-803      |
| `/standup-summary`  | daily standup digest             | FR-804      |
