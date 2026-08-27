"""Bounded exponential retry and dead-letter transitions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update

from .db import SqlStore, jobs
from .settings import get_settings


def record_failure(store: SqlStore, job_id: str, error: str) -> dict[str, Any]:
    """Record a failed attempt and schedule retry, or dead-letter at the cap."""
    settings = get_settings()
    with store.engine.begin() as connection:
        row = connection.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().first()
        if row is None:
            raise KeyError(f"job not found: {job_id}")
        attempts = int(row["attempts"] or 0)
        # A repeated failure report represents another attempt even when a test or
        # operator invokes this helper without passing through claim_job first.
        if row["status"] != "running":
            attempts += 1
        if attempts >= settings.job_max_attempts:
            values = {
                "status": "dead_letter", "attempts": attempts, "error": error,
                "finished_at": datetime.now(timezone.utc).isoformat(), "next_retry_at": None,
            }
            backoff = None
        else:
            backoff = min(
                settings.job_retry_base_seconds * (2 ** max(0, attempts - 1)),
                settings.job_retry_max_seconds,
            )
            values = {
                "status": "retry_wait", "attempts": attempts, "error": error,
                "finished_at": None,
                "next_retry_at": (datetime.now(timezone.utc) + timedelta(seconds=backoff)).isoformat(),
            }
        connection.execute(update(jobs).where(jobs.c.job_id == job_id).values(**values))
        updated = connection.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().one()
    result = dict(updated)
    if backoff is not None:
        result["backoff_seconds"] = backoff
    return result


def manual_retry(store: SqlStore, job_id: str) -> dict[str, Any] | None:
    """Requeue a dead-lettered job with a fresh attempt budget."""
    with store.engine.begin() as connection:
        result = connection.execute(
            update(jobs).where(
                jobs.c.job_id == job_id,
                jobs.c.status.in_(("failed", "dead_letter", "dead-letter")),
            ).values(
                status="queued", attempts=0, error=None, finished_at=None, next_retry_at=None
            )
        )
        if not result.rowcount:
            return None
        row = connection.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().one()
    return dict(row)
