"""Application settings loaded from the environment.

Single source of truth for runtime configuration. Loaded once at startup,
immutable thereafter. Never log this object directly: it carries secrets.
The HTTPS check on `JIRA_BASE_URL` is intentional and matches NFR-302; we
refuse to talk to Jira over plaintext even in dev, because it's the easiest
mistake to make and the worst one to ship.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Loaded once at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Jira
    jira_base_url: HttpUrl
    jira_auth_mode: Literal["api_token", "oauth"] = "api_token"

    # API-token mode
    jira_email: str | None = None
    jira_api_token: SecretStr | None = None

    # OAuth mode
    jira_oauth_client_id: str | None = None
    jira_oauth_client_secret: SecretStr | None = None
    jira_oauth_redirect_uri: str | None = None
    jira_oauth_scopes: str = "read:jira-work write:jira-work read:jira-user offline_access"

    # MongoDB
    mongo_uri: str
    mongo_db: str = "jira_mcp"

    # MCP transport
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = 8765
    # NoDecode tells pydantic-settings to skip its built-in JSON parse for
    # this field so our `mode="before"` validator can split a comma-separated
    # env value cleanly.
    mcp_cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"],
    )

    # Behaviour
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    allow_delete_issues: bool = False
    cache_ttl_seconds: int = Field(300, ge=0)
    jira_max_concurrency: int = Field(8, ge=1, le=64)
    jira_max_retries: int = Field(3, ge=0, le=10)

    @field_validator("jira_base_url")
    @classmethod
    def _https_only(cls, v: HttpUrl) -> HttpUrl:
        """Reject non-HTTPS Jira URLs (NFR-302)."""
        if v.scheme != "https":
            msg = "JIRA_BASE_URL must use https://"
            raise ValueError(msg)
        return v

    @field_validator("mcp_cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        """Allow CORS origins to arrive as a comma-separated env string.

        Pydantic-settings reads env vars as strings, so the natural way to
        configure this list from a shell is `MCP_CORS_ORIGINS=a,b,c`. We
        accept that shape here, strip whitespace, and drop empties; lists
        passed programmatically pass through untouched.
        """
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    def assert_auth_complete(self) -> None:
        """Verify the chosen auth mode has every field it needs.

        Done as a method rather than a model validator because the missing
        field set depends on the auth mode and we want the error to name the
        exact variables the operator must set.
        """
        if self.jira_auth_mode == "api_token":
            if not self.jira_email or not self.jira_api_token:
                msg = "api_token mode requires JIRA_EMAIL and JIRA_API_TOKEN"
                raise ValueError(msg)
        elif self.jira_auth_mode == "oauth":
            missing = [
                name
                for name, val in (
                    ("JIRA_OAUTH_CLIENT_ID", self.jira_oauth_client_id),
                    ("JIRA_OAUTH_CLIENT_SECRET", self.jira_oauth_client_secret),
                    ("JIRA_OAUTH_REDIRECT_URI", self.jira_oauth_redirect_uri),
                )
                if not val
            ]
            if missing:
                msg = f"oauth mode requires: {', '.join(missing)}"
                raise ValueError(msg)


def load_settings() -> Settings:
    """Load and validate settings. Call once at startup."""
    settings = Settings()
    settings.assert_auth_complete()
    return settings
