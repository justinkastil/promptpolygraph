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

from typing import TYPE_CHECKING, Any

__all__ = ["Settings", "get_settings"]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .settings import Settings, get_settings


def __getattr__(name: str) -> Any:
    """Resolve ``Settings``/``get_settings`` lazily (PEP 562).

    ``.settings`` needs ``pydantic-settings`` from the optional ``[service]``
    extra. The core engine has no such dependency, yet
    ``promptpolygraph.runner.store`` imports the stdlib-only
    ``promptpolygraph.service.privacy`` for #50 PII redaction on ingest --
    which executes this ``__init__``. Deferring the import keeps that path
    working on a core-only install while ``from promptpolygraph.service import
    get_settings`` behaves exactly as before. Unknown names raise
    ``AttributeError`` so the import machinery still falls back to loading
    submodules (``from promptpolygraph.service import metrics``, ...).
    """
    if name in __all__:
        from . import settings as _settings

        return getattr(_settings, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
