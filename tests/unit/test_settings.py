"""Settings validation tests.

These tests pin the contract for environment-driven configuration: HTTPS
is required, api-token mode demands email plus token, and oauth mode
must name the exact missing variables.
"""

from __future__ import annotations

import pytest

try:
    from jira_mcp.config.settings import Settings, load_settings
except ImportError:  # pragma: no cover - migration fallback
    from config.settings import Settings, load_settings  # type: ignore[no-redef]


_REQUIRED_KEYS = (
    "JIRA_BASE_URL",
    "JIRA_AUTH_MODE",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "JIRA_OAUTH_CLIENT_ID",
    "JIRA_OAUTH_CLIENT_SECRET",
    "JIRA_OAUTH_REDIRECT_URI",
    "MONGO_URI",
    "MONGO_DB",
)


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip any inherited Jira env so each test starts from a known floor."""
    for key in _REQUIRED_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_https_is_required(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Reject a non-HTTPS Jira base URL (NFR-302).

    Verifies that Settings construction fails when JIRA_BASE_URL uses
    plaintext HTTP, since the server refuses to talk to Jira over an
    untrusted channel even in development.
    """
    _clean_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRA_BASE_URL", "http://example.atlassian.net")
    monkeypatch.setenv("JIRA_AUTH_MODE", "api_token")
    monkeypatch.setenv("JIRA_EMAIL", "alice@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    with pytest.raises(ValueError, match="https"):
        Settings()  # type: ignore[call-arg]


def test_api_token_mode_accepts_complete_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Accept a fully-populated api_token configuration (FR-103).

    Verifies that load_settings returns a Settings instance when every
    required api-token variable is present and the URL is HTTPS.
    """
    _clean_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_AUTH_MODE", "api_token")
    monkeypatch.setenv("JIRA_EMAIL", "alice@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret-token")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("MONGO_DB", "jira_mcp_test")

    settings = load_settings()

    assert settings.jira_auth_mode == "api_token"
    assert settings.jira_email == "alice@example.com"
    assert settings.jira_api_token is not None
    assert settings.jira_api_token.get_secret_value() == "secret-token"
    assert str(settings.jira_base_url).startswith("https://")


def test_api_token_mode_missing_email_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Raise a clear ValueError when JIRA_EMAIL is missing (FR-103, FR-203).

    Verifies that load_settings fails fast when api_token mode is
    selected but the operator forgot to set the email variable.
    """
    _clean_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_AUTH_MODE", "api_token")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret-token")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")

    with pytest.raises(ValueError, match="JIRA_EMAIL"):
        load_settings()


def test_api_token_mode_missing_token_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Raise a clear ValueError when JIRA_API_TOKEN is missing (FR-103, FR-203).

    Verifies that load_settings fails fast when api_token mode is
    selected but the operator forgot to set the token variable.
    """
    _clean_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_AUTH_MODE", "api_token")
    monkeypatch.setenv("JIRA_EMAIL", "alice@example.com")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")

    with pytest.raises(ValueError, match="JIRA_API_TOKEN"):
        load_settings()


def test_oauth_mode_names_missing_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Name every missing OAuth variable in the error (FR-103, FR-203).

    Verifies that oauth mode raises ValueError listing each missing
    OAuth variable by name so the operator can fix them in one pass.
    """
    _clean_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_AUTH_MODE", "oauth")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")

    with pytest.raises(ValueError) as exc:
        load_settings()

    message = str(exc.value)
    assert "JIRA_OAUTH_CLIENT_ID" in message
    assert "JIRA_OAUTH_CLIENT_SECRET" in message
    assert "JIRA_OAUTH_REDIRECT_URI" in message
