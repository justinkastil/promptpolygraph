"""Service configuration via environment variables (prefix POLYGRAPH_).

Examples:
    POLYGRAPH_DATABASE_URL=postgresql+psycopg://user:pw@host/db
    POLYGRAPH_API_KEYS=key-alice,key-bob
    POLYGRAPH_OUT_DIR=/data/out
    POLYGRAPH_DATA_RESIDENCY=eu
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DataResidency = Literal["eu", "us", "none"]


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
    worker_poll_s: float = 2.0
    worker_concurrency: int = 1  # jobs processed at once per worker
    job_max_attempts: int = 3
    job_retry_base_seconds: int = 1
    job_retry_max_seconds: int = 300
    shutdown_drain_seconds: float = 30.0

    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800
    db_connect_timeout: int = 10
    db_statement_timeout: int = 30000
    job_retention_days: int = 30
    run_retention_days: int = 90

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

    # Per-workspace admission ceilings. These deliberately have generous,
    # backward-compatible defaults; operators opt into tighter limits with
    # POLYGRAPH_MAX_CONCURRENT_RUNS, POLYGRAPH_JOBS_PER_DAY, and
    # POLYGRAPH_MONTHLY_COST_BUDGET.
    max_concurrent_runs: int = 100
    jobs_per_day: int = 10000
    monthly_cost_budget: float = 10000.0

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

    # Data residency of stored run/response data (GitHub #50). Declarative: it
    # records the region the operator has committed to storing this deployment's
    # data in, so the dashboard, docs and audits can state it. It does not by
    # itself move data — pointing POLYGRAPH_DATABASE_URL and POLYGRAPH_OUT_DIR
    # at in-region storage is the operator's job. See docs/PRIVACY.md.
    #
    # Default "none" is the safe one: it asserts no guarantee rather than
    # silently claiming a region the storage may not honour. Override with
    # POLYGRAPH_DATA_RESIDENCY=eu|us|none (case/whitespace-insensitive).
    data_residency: DataResidency = "none"

    # Presentation.
    title: str = "PromptPolygraph"

    @field_validator("data_residency", mode="before")
    @classmethod
    def _normalize_data_residency(cls, value: Any) -> Any:
        """Accept ``EU``/`` us ``/unset from the environment; reject typos loudly.

        An unset or blank env var means "no commitment", i.e. the default. An
        unrecognised value is left for ``Literal`` validation to reject rather
        than being coerced to "none": an operator who wrote ``eur`` intended a
        guarantee, and silently downgrading it would be the wrong failure.
        """
        if value is None:
            return "none"
        if isinstance(value, str):
            return value.strip().lower() or "none"
        return value

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key_set)


@lru_cache
def get_settings() -> Settings:
    return Settings()
