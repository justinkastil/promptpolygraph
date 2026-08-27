"""Service configuration via environment variables (prefix POLYGRAPH_).

Examples:
    POLYGRAPH_DATABASE_URL=postgresql+psycopg://user:pw@host/db
    POLYGRAPH_API_KEYS=key-alice,key-bob
    POLYGRAPH_OUT_DIR=/data/out
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POLYGRAPH_", env_file=".env", extra="ignore")

    # Storage. sqlite:///... for local/dev, postgresql+psycopg://... for prod.
    database_url: str = "sqlite:///polygraph_service.sqlite"
    out_dir: str = "polygraph_out"

    # Where named configs live (a directory of <name>.yaml the API can launch).
    config_dir: str = "configs"

    # Auth. Comma-separated API keys; empty disables auth (dev only).
    api_keys: str = ""

    # Execution defaults.
    default_mock: bool = False
    worker_poll_s: float = Field(default=2.0, gt=0)
    worker_concurrency: int = Field(default=1, ge=1)  # jobs processed at once per worker
    job_max_attempts: int = Field(default=3, ge=1)
    job_retry_base_seconds: int = Field(default=30, ge=1)
    job_retry_max_seconds: int = Field(default=3600, ge=1)
    shutdown_drain_seconds: float = Field(default=30.0, ge=0)

    # Database connection/pool safeguards.
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_recycle: int = Field(default=1800, ge=0)
    db_connect_timeout: int = Field(default=10, ge=1)
    db_statement_timeout: int = Field(default=30000, ge=1)

    # Lifecycle cleanup. Zero disables deletion for that record type.
    job_retention_days: int = Field(default=30, ge=0)
    run_retention_days: int = Field(default=90, ge=0)

    # When true, the API process also runs a background worker thread — handy
    # for single-container / local use. In production run dedicated workers and
    # set this False (POLYGRAPH_INPROCESS_WORKER=0).
    inprocess_worker: bool = True

    # Optional cron schedules file (YAML). When set, the API starts a scheduler.
    schedules_path: str | None = None

    # Dependency probes are opt-in so ordinary startup never creates network I/O.
    startup_llm_check: bool = False
    readiness_llm_check: bool = False
    queue_max_depth: int = 1000

    # Optional global webhook fired on every run completion.
    webhook_url: str | None = None

    # Optional OIDC/OAuth2 SSO (human login). Unset -> disabled; API-key auth is
    # unchanged. Needs the [oidc] extra. The IdP issues a bearer JWT we verify
    # against its JWKS and map (by email/sub) to a workspace member's role.
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""          # optional; derived from the issuer when blank
    oidc_email_claim: str = "email"
    oidc_require_mfa: bool = False   # enforce an MFA amr/acr claim

    # Presentation.
    title: str = "PromptPolygraph"

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key_set)


@lru_cache
def get_settings() -> Settings:
    return Settings()
