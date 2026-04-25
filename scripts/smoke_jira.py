"""End-to-end smoke against a real Jira Cloud instance.

Exercises the read paths of every domain client using the credentials in
`.env`. Writes are skipped by default; pass `--include-writes` to also create
a temporary issue, comment on it, transition it, and clean up. The cleanup
step needs `ALLOW_DELETE_ISSUES=true`, otherwise the temporary issue is
left behind for manual review.

Usage:
    PYTHONPATH=src python scripts/smoke_jira.py
    PYTHONPATH=src python scripts/smoke_jira.py --include-writes
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import certifi
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from jira_mcp.auth.api_token import ApiTokenAuth  # noqa: E402
from jira_mcp.clients.issues import IssueClient  # noqa: E402
from jira_mcp.clients.jira import JiraClient  # noqa: E402
from jira_mcp.clients.projects import ProjectClient  # noqa: E402
from jira_mcp.clients.sprints import SprintClient  # noqa: E402
from jira_mcp.clients.users import UserClient  # noqa: E402
from jira_mcp.config.settings import load_settings  # noqa: E402
from jira_mcp.models.tool_io import CreateIssueInput  # noqa: E402


def _load_dotenv() -> None:
    """Load .env into os.environ so load_settings() picks it up."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        sys.exit(".env not found at repo root")
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_PASS = "[ok] "
_FAIL = "[!!] "


def _ok(msg: str) -> None:
    print(_PASS + msg)


def _fail(msg: str) -> None:
    print(_FAIL + msg)


async def _myself(jira: JiraClient) -> dict[str, Any]:
    me = await jira.get("/rest/api/3/myself")
    _ok(f"myself: {me.get('displayName')} <{me.get('emailAddress')}>")
    return me


async def _projects(client: ProjectClient) -> list[Any]:
    projects = await client.list_projects()
    _ok(f"list_projects: {len(projects)} project(s)")
    if projects:
        first = projects[0]
        _ok(f"  first project: key={first.key} id={first.id} name={first.name}")
        detail = await client.get(first.key)
        _ok(f"  get_project({first.key}): name={detail.name}")
    return projects


async def _users(client: UserClient, my_email: str) -> None:
    users = await client.list_users()
    _ok(f"list_users: {len(users)} user(s)")
    resolved = await client.resolve(my_email)
    if resolved is None:
        _fail(f"resolve({my_email}) returned None")
    else:
        _ok(f"resolve({my_email}): accountId={resolved.account_id}")


async def _custom_fields(client: ProjectClient) -> None:
    out = await client.list_custom_fields()
    _ok(f"list_custom_fields: {len(out.fields)} custom field(s)")


async def _search(client: IssueClient, project_key: str | None) -> str | None:
    jql = f"project = {project_key} ORDER BY updated DESC" if project_key else "ORDER BY updated DESC"
    out = await client.search(jql, max_results=5)
    _ok(f"search_issues('{jql}'): total={out.total} returned={len(out.issues)}")
    if out.issues:
        first_key = out.issues[0].key
        issue = await client.get(first_key, expand=["transitions"])
        _ok(f"  get_issue({first_key}): status={issue.status.name if issue.status else 'n/a'}")
        return first_key
    return None


async def _boards_sprints(client: SprintClient) -> None:
    boards = await client.list_boards()
    _ok(f"list_boards: {len(boards)} board(s)")
    if not boards:
        return
    board = boards[0]
    _ok(f"  first board: id={board.id} name={board.name} type={board.type}")
    sprints = await client.list_sprints(board.id)
    _ok(f"  list_sprints(board={board.id}): {len(sprints)} sprint(s)")
    if sprints:
        sprint = sprints[0]
        s = await client.get_sprint(sprint.id)
        _ok(f"  get_sprint({sprint.id}): state={s.state} name={s.name}")


async def _writes(client: IssueClient, project_key: str) -> None:
    summary = "MCP smoke test (safe to delete)"
    created = await client.create(
        CreateIssueInput(
            project_key=project_key,
            summary=summary,
            issue_type="Task",
            description="Created by scripts/smoke_jira.py to verify write paths.",
        )
    )
    _ok(f"create_issue: key={created.key} id={created.id}")

    comment = await client.add_comment(created.key, "Smoke comment")
    _ok(f"add_comment({created.key}): id={comment.id}")

    transitions = await client.list_transitions(created.key)
    _ok(f"list_transitions({created.key}): {len(transitions.transitions)} option(s)")

    if transitions.transitions:
        first = transitions.transitions[0]
        await client.transition(created.key, first.id, comment="smoke")
        _ok(f"transition_issue({created.key} -> '{first.name}'): ok")

    if os.environ.get("ALLOW_DELETE_ISSUES") == "true":
        await client.delete(created.key)
        _ok(f"delete_issue({created.key}): ok")
    else:
        print(f"     (left {created.key} in Jira; set ALLOW_DELETE_ISSUES=true to clean up)")


async def main(include_writes: bool) -> int:
    _load_dotenv()
    settings = load_settings()
    if settings.jira_email is None or settings.jira_api_token is None:
        sys.exit("api_token mode requires JIRA_EMAIL and JIRA_API_TOKEN in .env")

    auth = ApiTokenAuth(settings.jira_email, settings.jira_api_token)
    transport = httpx.AsyncHTTPTransport(verify=certifi.where())
    failures = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(30), transport=transport) as http:
        jira = JiraClient(str(settings.jira_base_url), auth, http)
        issues = IssueClient(jira)
        projects = ProjectClient(jira)
        users = UserClient(jira)
        sprints = SprintClient(jira)

        steps: list[tuple[str, Any]] = [
            ("myself", _myself(jira)),
        ]
        try:
            me = await steps[0][1]
        except Exception as exc:
            _fail(f"myself: {exc!r}")
            return 1

        my_email = me.get("emailAddress") or settings.jira_email
        first_project_key: str | None = None

        try:
            project_list = await _projects(projects)
            first_project_key = project_list[0].key if project_list else None
        except Exception as exc:
            _fail(f"projects: {exc!r}")
            failures += 1

        for label, coro in (
            ("users", _users(users, my_email)),
            ("custom_fields", _custom_fields(projects)),
            ("search/get", _search(issues, first_project_key)),
            ("boards/sprints", _boards_sprints(sprints)),
        ):
            try:
                await coro
            except Exception as exc:
                _fail(f"{label}: {exc!r}")
                failures += 1

        if include_writes:
            if first_project_key is None:
                _fail("writes skipped: no project available")
                failures += 1
            else:
                try:
                    await _writes(issues, first_project_key)
                except Exception as exc:
                    _fail(f"writes: {exc!r}")
                    failures += 1

    print()
    if failures:
        print(f"smoke: {failures} step(s) failed")
        return 1
    print("smoke: all steps passed")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-writes", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.include_writes)))
