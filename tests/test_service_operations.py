from __future__ import annotations

import sqlite3
from pathlib import Path

from promptpolygraph.service import backup, retention
from promptpolygraph.service.db import SqlStore
from promptpolygraph.service.retry import manual_retry, record_failure
from promptpolygraph.service.settings import get_settings


def test_failure_backoff_dead_letter_and_manual_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYGRAPH_JOB_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("POLYGRAPH_JOB_RETRY_BASE_SECONDS", "1")
    get_settings.cache_clear()
    store = SqlStore(f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    seeded = store.enqueue_job({"mock": True})
    store.claim_job()
    first = record_failure(store, seeded["job_id"], "temporary")
    assert first["status"] == "retry_wait"
    assert first["backoff_seconds"] == 1
    final = record_failure(store, seeded["job_id"], "again")
    assert final["status"] == "dead_letter"
    assert manual_retry(store, seeded["job_id"])["status"] == "queued"
    get_settings.cache_clear()


def test_retention_and_restorable_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYGRAPH_JOB_RETENTION_DAYS", "1")
    get_settings.cache_clear()
    db_path = tmp_path / "service.sqlite"
    store = SqlStore(f"sqlite:///{db_path}")
    seeded = store.enqueue_job({"mock": True})
    from sqlalchemy import update
    from promptpolygraph.service.db import jobs
    with store.engine.begin() as connection:
        connection.execute(update(jobs).where(jobs.c.job_id == seeded["job_id"]).values(
            created_at="2000-01-01T00:00:00Z"
        ))
    assert retention.purge(store)["jobs"] == 1
    snapshot = backup.create_snapshot(store, tmp_path / "snapshots")
    with sqlite3.connect(snapshot) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    get_settings.cache_clear()
