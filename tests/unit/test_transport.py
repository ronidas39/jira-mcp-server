"""Tests for the transport selection layer.

Covers the streamable HTTP path: we monkeypatch `uvicorn.Server.serve` to
a no-op coroutine so the test never binds a real socket, then call the
top-level `run` function and assert the Starlette app is built and the
serve loop is reached without raising.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from mcp.server import Server

from jira_mcp.config.settings import Settings
from jira_mcp.server import transport


def _make_settings(**overrides: Any) -> Settings:
    """Build a Settings instance with HTTP transport defaults.

    Settings has required fields (jira_base_url, mongo_uri, etc.); we set
    minimums for an api_token configuration and let callers override what
    matters to a particular test.
    """
    base: dict[str, Any] = {
        "jira_base_url": "https://example.atlassian.net",
        "jira_auth_mode": "api_token",
        "jira_email": "alice@example.com",
        "jira_api_token": "secret",
        "mongo_uri": "mongodb://localhost:27017",
        "mcp_transport": "http",
        "mcp_http_host": "127.0.0.1",
        "mcp_http_port": 0,
        "mcp_cors_origins": ["http://localhost:3000"],
    }
    base.update(overrides)
    return Settings(**base)


def _make_ctx() -> SimpleNamespace:
    """Build a ServerContext-shaped stub with a real low-level MCP Server.

    Constructing a real `Server` is cheap and lets the session manager
    initialise without us mocking its protocol surface; everything else on
    the ctx is unused on the HTTP path so a SimpleNamespace is enough.
    """
    return SimpleNamespace(server=Server(name="jira-mcp-test", version="0.0.0"))


async def test_http_transport_builds_app_and_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The http branch builds a Starlette app and reaches `server.serve()`.

    Verifies that selecting MCP_TRANSPORT=http wires the streamable HTTP
    session manager into a Starlette app without raising, and that the
    uvicorn serve loop is invoked exactly once. The serve coroutine is a
    no-op so no socket is ever bound.
    """
    import uvicorn  # noqa: PLC0415

    serve_calls: list[uvicorn.Server] = []

    async def fake_serve(self: uvicorn.Server) -> None:
        """Stand-in for uvicorn.Server.serve that records the call."""
        serve_calls.append(self)

    monkeypatch.setattr(uvicorn.Server, "serve", fake_serve)

    ctx = _make_ctx()
    settings = _make_settings()

    await transport.run(ctx, settings)  # type: ignore[arg-type]

    assert len(serve_calls) == 1
    served = serve_calls[0]
    assert served.config.host == "127.0.0.1"
    assert served.config.port == 0


async def test_unknown_transport_raises() -> None:
    """An unknown transport value is rejected with a clear ValueError.

    The Settings model already restricts MCP_TRANSPORT to a literal, so
    this guards the runtime branch when callers construct Settings
    programmatically and bypass that validation.
    """
    ctx = _make_ctx()
    settings = _make_settings()
    object.__setattr__(settings, "mcp_transport", "ftp")

    with pytest.raises(ValueError, match="unsupported MCP_TRANSPORT"):
        await transport.run(ctx, settings)  # type: ignore[arg-type]


def test_build_http_app_applies_cors_origins() -> None:
    """The Starlette app honours the configured CORS origin allowlist.

    Verifies that `_build_http_app` produces a Starlette app whose user
    middleware stack contains CORSMiddleware configured with the origins
    from settings; this is the contract the browser-side UI depends on.
    """
    from starlette.middleware.cors import CORSMiddleware  # noqa: PLC0415

    ctx = _make_ctx()
    settings = _make_settings(mcp_cors_origins=["http://localhost:3000", "https://ui.example"])

    app = transport._build_http_app(ctx, settings)  # type: ignore[arg-type]

    cors_layers = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors_layers) == 1
    cors = cors_layers[0]
    assert cors.kwargs["allow_origins"] == [
        "http://localhost:3000",
        "https://ui.example",
    ]
    assert "Mcp-Session-Id" in cors.kwargs["allow_headers"]
    assert "Mcp-Session-Id" in cors.kwargs["expose_headers"]
    assert set(cors.kwargs["allow_methods"]) == {"GET", "POST", "DELETE", "OPTIONS"}


def test_settings_parses_comma_separated_cors_origins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A comma-separated MCP_CORS_ORIGINS env value loads as a list.

    Verifies the field validator splits on commas, trims whitespace, and
    drops empty fragments, so operators can configure the allowlist with
    a single shell-friendly variable.
    """
    for key in (
        "JIRA_BASE_URL",
        "JIRA_EMAIL",
        "JIRA_API_TOKEN",
        "MONGO_URI",
        "MCP_CORS_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_AUTH_MODE", "api_token")
    monkeypatch.setenv("JIRA_EMAIL", "alice@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setenv(
        "MCP_CORS_ORIGINS",
        "http://localhost:3000, https://ui.example , ",
    )

    settings = Settings()  # type: ignore[call-arg]
    assert settings.mcp_cors_origins == [
        "http://localhost:3000",
        "https://ui.example",
    ]
