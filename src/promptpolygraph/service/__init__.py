"""Service layer — a deployable API + worker that wraps the core engine.

The core (corpus -> runner -> analyze -> audit -> report) is a pure library.
This package adds, without changing the engine:

  - `SqlStore`  : the `Store` protocol over any SQLAlchemy URL (sqlite/postgres)
                  plus a durable job queue.
  - `pipeline`  : a store-driven run -> analyze -> audit -> report orchestration.
  - FastAPI app : trigger runs, poll status, fetch reports, compare, manage
                  personas — behind API-key auth, with a server-rendered dashboard.
  - worker      : claims queued jobs and executes the pipeline; scale horizontally.
  - scheduler   : cron-enqueue recurring runs.

One Docker image runs either role (api or worker), against sqlite locally or
Postgres in production, on AWS or GCP.
"""

from __future__ import annotations

from .settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
