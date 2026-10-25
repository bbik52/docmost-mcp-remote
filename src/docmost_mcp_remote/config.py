"""Server settings, read from environment variables and validated at startup."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
_MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """All configuration of the server.

    Required values have no default, so a missing variable fails at startup
    instead of at the first request.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    public_url: AnyHttpUrl = Field(
        description="Public https URL where MCP clients reach this server.",
    )
    docmost_url: AnyHttpUrl = Field(
        description="Base URL of the Docmost instance this server works with.",
    )
    docmost_allow_insecure_http: bool = Field(
        default=False,
        description="Allow an http:// DOCMOST_URL, for a Docmost on a trusted private network.",
    )
    docmost_timeout_seconds: float = Field(
        default=15.0,
        gt=0,
        le=120,
        description="Timeout for one request to Docmost.",
    )
    docmost_max_response_bytes: int = Field(
        default=5 * 1024 * 1024,
        ge=64 * 1024,
        description="Largest Docmost response the server reads; larger answers fail.",
    )
    database_url: SecretStr = Field(
        description="Postgres connection URL, for example postgresql://user:pass@host/db.",
    )
    secret_key: SecretStr = Field(
        description="Key for encrypting stored Docmost sessions and signing cookies.",
    )
    secret_key_previous: SecretStr | None = Field(
        default=None,
        description="Previous SECRET_KEY during a key rotation; only used to decrypt.",
    )
    allowed_emails: Annotated[frozenset[str], NoDecode] = Field(
        default=frozenset(),
        description="Comma-separated emails allowed to sign in; empty allows every Docmost user.",
    )
    allowed_spaces: Annotated[frozenset[str], NoDecode] = Field(
        default=frozenset(),
        description="Comma-separated space slugs or ids members may use through this server; "
        "empty allows every space the member can see in Docmost.",
    )
    max_page_chars: int = Field(
        default=60_000,
        ge=1_000,
        le=1_000_000,
        description="Longest page body returned to a client; longer bodies are truncated.",
    )
    relogin_mode: Literal["ask", "stored_password"] = Field(
        default="ask",
        description="On an expired Docmost session: ask the member to sign in again, or sign "
        "in again with an encrypted stored password.",
    )
    web_session_hours: int = Field(default=12, ge=1, le=24 * 7)
    host: str = "0.0.0.0"  # noqa: S104 - the server runs in a container behind a reverse proxy
    port: int = Field(default=8000, ge=1, le=65535)
    forwarded_allow_ips: str = Field(
        default="127.0.0.1",
        description="Proxies whose X-Forwarded-For header is trusted (uvicorn syntax).",
    )
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    @field_validator("public_url")
    @classmethod
    def _public_url_is_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https" and value.host not in _LOCAL_HOSTS:
            raise ValueError("PUBLIC_URL must use https (http is only accepted for localhost)")
        return value

    @field_validator("secret_key_previous", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("secret_key", "secret_key_previous")
    @classmethod
    def _secret_is_long(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < _MIN_SECRET_LENGTH:
            raise ValueError(f"must be at least {_MIN_SECRET_LENGTH} characters")
        return value

    @field_validator("database_url")
    @classmethod
    def _database_is_postgres(cls, value: SecretStr) -> SecretStr:
        scheme = value.get_secret_value().split("://", 1)[0]
        if scheme not in ("postgres", "postgresql", "postgresql+asyncpg"):
            raise ValueError("DATABASE_URL must be a postgresql:// URL")
        return value

    @field_validator("allowed_spaces", mode="before")
    @classmethod
    def _split_spaces(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("allowed_emails", mode="before")
    @classmethod
    def _split_emails(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(part.strip().lower() for part in value.split(",") if part.strip())
        if isinstance(value, list | set | frozenset | tuple):
            return frozenset(str(part).strip().lower() for part in value)
        return value

    @model_validator(mode="after")
    def _docmost_url_is_https(self) -> Settings:
        if self.docmost_url.scheme != "https" and not self.docmost_allow_insecure_http:
            raise ValueError(
                "DOCMOST_URL must use https; set DOCMOST_ALLOW_INSECURE_HTTP=true "
                "to allow http on a trusted private network"
            )
        return self

    @property
    def docmost_url_is_insecure(self) -> bool:
        return self.docmost_url.scheme != "https"

    @property
    def public_url_is_https(self) -> bool:
        return self.public_url.scheme == "https"

    @property
    def public_base(self) -> str:
        """``PUBLIC_URL`` without a trailing slash."""
        return str(self.public_url).rstrip("/")

    def email_allowed(self, email: str) -> bool:
        return not self.allowed_emails or email.strip().lower() in self.allowed_emails
