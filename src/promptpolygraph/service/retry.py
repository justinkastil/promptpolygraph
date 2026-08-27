"""Retry and dead-letter state transitions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy import select, update
from .db import SqlStore, jobs


def record_failure(store: SqlStore, job_id: str, error: str) -> dict[str, Any]:
    with store.engine.begin() as connection:
        row = connection.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().first()
        if row is None:
            raise KeyError(job_id)
        attempts = int(row["attempts"] or 0)
        # Normal workers increment on claim.  Direct callers may record a
        # subsequent queued/retry-wait failure without claiming first.
        if row["status"] != "running":
            attempts += 1
        settings = store.settings
        if attempts < settings.job_max_attempts:
            delay = min(settings.job_retry_base_seconds * (2 ** max(0, attempts - 1)),
                        settings.job_retry_max_seconds)
            next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            values = {"status": "queued", "attempts": attempts,
                      "error": error, "finished_at": None,
                      "next_retry_at": next_at, "backoff_seconds": delay}
        else:
            values = {"status": "dead_letter", "attempts": attempts, "error": error,
                      "finished_at": datetime.now(timezone.utc).isoformat(),
                      "next_retry_at": None, "backoff_seconds": None}
        connection.execute(update(jobs).where(jobs.c.job_id == job_id).values(**values))
        updated = connection.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().one()
    return dict(updated)
