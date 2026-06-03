"""Request/response models for the service API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    """Trigger a run. Provide exactly one of config / config_path / config_name."""

    config: dict[str, Any] | None = Field(default=None, description="inline Config dict")
    config_path: str | None = Field(default=None, description="absolute path to a config.yaml")
    config_name: str | None = Field(default=None, description="name of a config in the server's config_dir")
    overrides: dict[str, Any] | None = Field(
        default=None,
        description="corpus/run dials: mode, count, per_category, categories, difficulty, concurrency, judges",
    )
    mock: bool | None = None
    priority: int = 0
    webhook_url: str | None = Field(default=None, description="POSTed a summary when the run finishes")
    formats: list[str] | None = Field(default=None, description="report formats, e.g. ['md','html','pdf']")


class CreateRunResponse(BaseModel):
    run_id: str
    job_id: str
    status: str


class RunStatus(BaseModel):
    run_id: str
    job_id: str | None = None
    status: str  # queued | running | done | failed | canceled | unknown
    mode: str | None = None
    adapter: str | None = None
    progress: dict[str, Any] | None = None
    error: str | None = None
    total_cases: int | None = None
    completed_cases: int | None = None
    overall_pass: bool | None = None
    created_at: str | None = None
    completed_at: str | None = None


class RunSummary(BaseModel):
    run_id: str
    summary: dict[str, Any] | None = None
    reports: dict[str, str] | None = None


class JobInfo(BaseModel):
    job_id: str
    run_id: str
    status: str
    attempts: int
    error: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class PersonaOut(BaseModel):
    id: str
    who: str
    focus: str = ""


class CreatePersonaRequest(BaseModel):
    description: str
    mock: bool | None = None


class PairwiseResponse(BaseModel):
    run_a: str
    run_b: str
    wins_a: int
    wins_b: int
    ties: int
    by_category: dict[str, Any] = {}
