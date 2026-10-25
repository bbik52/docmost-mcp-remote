"""Server settings, read from environment variables and validated at startup."""

from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


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
    database_url: str | None = Field(
        default=None,
        description="Postgres connection URL. Required from the release that adds Member sign-in.",
    )
    host: str = "0.0.0.0"  # noqa: S104 - the server runs in a container behind a reverse proxy
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    @field_validator("public_url")
    @classmethod
    def _public_url_is_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https" and value.host not in _LOCAL_HOSTS:
            raise ValueError("PUBLIC_URL must use https (http is only accepted for localhost)")
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
