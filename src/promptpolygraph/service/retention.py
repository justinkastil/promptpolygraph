"""Retention cleanup that preserves queued and running work."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select
from .db import SqlStore, cases, jobs, responses, runs, scores


def purge(store: SqlStore) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    job_cutoff = (now - timedelta(days=store.settings.job_retention_days)).isoformat()
    run_cutoff = (now - timedelta(days=store.settings.run_retention_days)).isoformat()
    # A running job is in-flight and must never be removed. Queued jobs older
    # than the configured retention horizon are abandoned work and eligible.
    active = ("running",)
    with store.engine.begin() as connection:
        job_result = connection.execute(delete(jobs).where(
            jobs.c.created_at < job_cutoff, jobs.c.status.not_in(active)))
        protected = select(jobs.c.run_id).where(jobs.c.status.in_(active))
        old_runs = [row[0] for row in connection.execute(select(runs.c.run_id).where(
            runs.c.created_at < run_cutoff, runs.c.run_id.not_in(protected))).all()]
        for table in (cases, responses, scores):
            if old_runs:
                connection.execute(delete(table).where(table.c.run_id.in_(old_runs)))
        if old_runs:
            connection.execute(delete(runs).where(runs.c.run_id.in_(old_runs)))
    return {"jobs": job_result.rowcount or 0, "runs": len(old_runs)}
