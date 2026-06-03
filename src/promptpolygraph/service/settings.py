"""Service configuration via environment variables (prefix POLYGRAPH_).

Examples:
    POLYGRAPH_DATABASE_URL=postgresql+psycopg://user:pw@host/db
    POLYGRAPH_API_KEYS=key-alice,key-bob
    POLYGRAPH_OUT_DIR=/data/out
"""

from __future__ import annotations

from functools import lru_cache

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
    worker_poll_s: float = 2.0
    worker_concurrency: int = 1  # jobs processed at once per worker
    job_max_attempts: int = 1

    # When true, the API process also runs a background worker thread — handy
    # for single-container / local use. In production run dedicated workers and
    # set this False (POLYGRAPH_INPROCESS_WORKER=0).
    inprocess_worker: bool = True

    # Optional cron schedules file (YAML). When set, the API starts a scheduler.
    schedules_path: str | None = None

    # Optional global webhook fired on every run completion.
    webhook_url: str | None = None

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
