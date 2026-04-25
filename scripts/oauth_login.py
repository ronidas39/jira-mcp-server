"""One-shot OAuth login script for Atlassian Jira Cloud.

Performs the three-legged OAuth dance and persists the resulting tokens to
MongoDB so the running server can pick them up. The flow is:

1. Read OAuth client config from ``.env`` via ``load_settings``.
2. Generate a random ``state`` value for CSRF protection.
3. Start a local listener on the port encoded in
   ``JIRA_OAUTH_REDIRECT_URI`` to receive the redirect.
4. Print the authorize URL and try to open it via ``webbrowser``.
5. Wait for the callback, validate ``state``, exchange the ``code`` for
   tokens, fetch the tenant's ``cloud_id``, and persist the record.
6. Print ``ok cloud_id=<id>`` and exit zero.

Failures exit non-zero with a one-line error message. The script is meant
to run on a developer laptop, not inside the server process: it spawns a
short-lived HTTP listener and shuts down once the redirect is handled.

Usage:
    python scripts/oauth_login.py
"""

from __future__ import annotations

import asyncio
import secrets
import sys
import webbrowser
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

# The script is run from the repository root, so the ``src`` package layout
# resolves once the path is added explicitly.
_REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from jira_mcp.auth.oauth import (  # noqa: E402
    build_authorize_url,
    exchange_code_for_token,
    fetch_cloud_id,
)
from jira_mcp.config import load_settings  # noqa: E402
from jira_mcp.db.connection import MongoConnection  # noqa: E402
from jira_mcp.db.repositories.oauth_tokens import TokenRecord, TokenRepository  # noqa: E402


class _CallbackResult:
    """Mutable holder used by the callback handler to publish the OAuth result.

    The Starlette callback runs inside the uvicorn task; the orchestrator
    waits on ``done`` and then reads ``code`` or ``error``. Using an asyncio
    Event keeps the wait cheap and makes cancellation behave.
    """

    def __init__(self) -> None:
        self.done = asyncio.Event()
        self.code: str | None = None
        self.state: str | None = None
        self.error: str | None = None


def _parse_redirect(redirect_uri: str) -> tuple[str, int, str]:
    """Split the redirect URI into its host, port, and path components.

    Atlassian requires the redirect URI to match exactly what was registered
    with the OAuth app, so we honour the operator's value verbatim. Port
    defaults to 80 for http and 443 for https when the URI omits it; the
    listener binds to localhost regardless of the host name to keep the
    flow safe on shared networks.
    """
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    path = parsed.path or "/"
    return host, port, path


def _build_callback_app(state: str, result: _CallbackResult, callback_path: str) -> Starlette:
    """Build a single-route Starlette app that captures the OAuth redirect.

    Validates ``state`` to defeat CSRF: an attacker who can trick the user
    into hitting the redirect with a code they obtained for a different
    session would otherwise be able to bind their session to the user's
    Mongo record.
    """

    async def callback(request: Request) -> HTMLResponse:
        params = request.query_params
        received_state = params.get("state")
        if received_state != state:
            result.error = "state mismatch (possible CSRF)"
            result.done.set()
            return HTMLResponse(
                "<h1>OAuth error</h1><p>state mismatch</p>", status_code=400
            )
        if "error" in params:
            result.error = params.get("error_description") or params["error"]
            result.done.set()
            return HTMLResponse(
                f"<h1>OAuth error</h1><p>{result.error}</p>", status_code=400
            )
        code = params.get("code")
        if not code:
            result.error = "missing code in callback"
            result.done.set()
            return HTMLResponse(
                "<h1>OAuth error</h1><p>missing code</p>", status_code=400
            )
        result.code = code
        result.state = received_state
        result.done.set()
        return HTMLResponse(
            "<h1>Login complete.</h1><p>You can close this tab.</p>"
        )

    return Starlette(routes=[Route(callback_path, callback, methods=["GET"])])


async def _wait_for_callback(
    result: _CallbackResult, server: uvicorn.Server, timeout_s: float
) -> None:
    """Wait for the callback to complete and stop the listener.

    Splitting this out lets us put a sane timeout around the wait so the
    script does not hang forever if the user closes the browser without
    completing consent.
    """
    try:
        await asyncio.wait_for(result.done.wait(), timeout=timeout_s)
    finally:
        server.should_exit = True


async def _persist_token(
    body: dict[str, Any],
    cloud_id: str,
    scopes: str,
    mongo: MongoConnection,
) -> None:
    """Write the token record to Mongo via TokenRepository.

    Atlassian's response always includes ``access_token``, ``refresh_token``,
    ``expires_in``, and ``scope``; we trust those keys and surface a clean
    error if any are missing rather than silently storing partial state.
    """
    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    expires_in = int(body.get("expires_in", 0))
    if not isinstance(access_token, str) or not access_token:
        msg = "OAuth response missing access_token"
        raise RuntimeError(msg)
    if not isinstance(refresh_token, str) or not refresh_token:
        msg = "OAuth response missing refresh_token"
        raise RuntimeError(msg)
    granted_scope = body.get("scope")
    final_scopes = granted_scope if isinstance(granted_scope, str) and granted_scope else scopes
    now = datetime.now(tz=UTC)
    record = TokenRecord(
        _id=cloud_id,
        cloud_id=cloud_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=now + timedelta(seconds=expires_in),
        scopes=final_scopes,
        updated_at=now,
    )
    repo = TokenRepository(mongo.db)
    await repo.ensure_indexes()
    await repo.upsert(record)


def _validate_oauth_settings(settings: Any) -> int:
    """Return zero when OAuth settings are present, or a non-zero exit code.

    Pulled out to keep ``_run`` short. The function prints user-facing
    error messages directly to stderr because the script is interactive.
    """
    if settings.jira_auth_mode != "oauth":
        print("error: JIRA_AUTH_MODE must be 'oauth' to run this script", file=sys.stderr)
        return 2
    if (
        settings.jira_oauth_client_id is None
        or settings.jira_oauth_client_secret is None
        or settings.jira_oauth_redirect_uri is None
    ):
        print(
            "error: oauth client_id, client_secret, and redirect_uri are required",
            file=sys.stderr,
        )
        return 2
    return 0


async def _await_oauth_code(settings: Any, state: str, result: _CallbackResult) -> int:
    """Run the local listener, open the browser, and capture the callback.

    Returns zero on a successful capture, non-zero with a logged error
    otherwise.
    """
    host, port, path = _parse_redirect(settings.jira_oauth_redirect_uri)
    app = _build_callback_app(state, result, path)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
        access_log=False,
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())

    authorize_url = build_authorize_url(
        settings.jira_oauth_client_id,
        settings.jira_oauth_redirect_uri,
        settings.jira_oauth_scopes,
        state,
    )
    print(f"open this URL in your browser if it does not open automatically:\n{authorize_url}")
    try:
        webbrowser.open(authorize_url)
    except Exception:
        # webbrowser is best-effort; the printed URL is the canonical path.
        pass

    try:
        await _wait_for_callback(result, server, timeout_s=300.0)
    except asyncio.TimeoutError:
        print(
            f"error: timed out waiting for OAuth callback on {host}:{port}{path}",
            file=sys.stderr,
        )
        server.should_exit = True
        await serve_task
        return 1
    await serve_task
    if result.error or not result.code:
        print(f"error: oauth callback failed: {result.error}", file=sys.stderr)
        return 1
    return 0


async def _exchange_and_persist(settings: Any, code: str) -> int:
    """Exchange the code, find cloud_id, and persist the token. Returns exit code."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
        try:
            body = await exchange_code_for_token(
                http,
                settings.jira_oauth_client_id,
                settings.jira_oauth_client_secret.get_secret_value(),
                code,
                settings.jira_oauth_redirect_uri,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"error: token exchange failed: {exc}", file=sys.stderr)
            return 1
        try:
            cloud_id = await fetch_cloud_id(http, body["access_token"])
        except Exception as exc:  # noqa: BLE001
            print(f"error: accessible-resources lookup failed: {exc}", file=sys.stderr)
            return 1

    mongo = MongoConnection(settings.mongo_uri, settings.mongo_db)
    try:
        await _persist_token(body, cloud_id, settings.jira_oauth_scopes, mongo)
    except Exception as exc:  # noqa: BLE001
        print(f"error: token persistence failed: {exc}", file=sys.stderr)
        await mongo.close()
        return 1
    await mongo.close()
    print(f"ok cloud_id={cloud_id}")
    return 0


async def _run() -> int:
    """Drive the OAuth dance and return the process exit code."""
    settings = load_settings()
    rc = _validate_oauth_settings(settings)
    if rc != 0:
        return rc

    state = secrets.token_urlsafe(24)
    result = _CallbackResult()
    rc = await _await_oauth_code(settings, state, result)
    if rc != 0:
        return rc
    assert result.code is not None  # narrowed by _await_oauth_code's guard
    return await _exchange_and_persist(settings, result.code)


def main() -> None:
    """Synchronous entry point for the script."""
    try:
        code = asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(130)
    sys.exit(code)


if __name__ == "__main__":
    main()
