"""Retention cleanup for completed service records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from .db import SqlStore, cases, jobs, responses, runs, scores
from .settings import get_settings


def purge(store: SqlStore) -> dict[str, int]:
    """Delete jobs and runs older than configured retention windows."""
    settings = get_settings()
    result = {"jobs": 0, "runs": 0}
    with store.engine.begin() as connection:
        if settings.job_retention_days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.job_retention_days)).isoformat()
            deleted = connection.execute(delete(jobs).where(jobs.c.created_at < cutoff))
            result["jobs"] = deleted.rowcount
        if settings.run_retention_days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.run_retention_days)).isoformat()
            run_ids = list(connection.execute(
                select(runs.c.run_id).where(runs.c.created_at < cutoff)
            ).scalars())
            if run_ids:
                for table in (cases, responses, scores):
                    connection.execute(delete(table).where(table.c.run_id.in_(run_ids)))
                deleted = connection.execute(delete(runs).where(runs.c.run_id.in_(run_ids)))
                result["runs"] = deleted.rowcount
    return result
