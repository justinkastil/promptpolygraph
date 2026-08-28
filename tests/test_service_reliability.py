from __future__ import annotations

import sqlite3
import time

from sqlalchemy import insert, select, update

from promptpolygraph.service import shutdown
from promptpolygraph.service.backup import create_snapshot
from promptpolygraph.service.db import SqlStore, jobs, runs
from promptpolygraph.service.retention import purge
from promptpolygraph.service.retry import record_failure
from promptpolygraph.service.settings import Settings


def _store(tmp_path, **overrides):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'service.sqlite'}",
        job_retry_base_seconds=2,
        job_retry_max_seconds=20,
        job_retention_days=30,
        run_retention_days=30,
        **overrides,
    )
    return SqlStore(settings.database_url, settings=settings)


def test_retry_backoff_dead_letter_and_idempotent_manual_retry(tmp_path):
    store = _store(tmp_path, job_max_attempts=3)
    seeded = store.enqueue_job({"mock": True})
    assert store.claim_job() is not None
    first = record_failure(store, seeded["job_id"], "one")
    assert first["status"] == "queued"
    assert first["backoff_seconds"] == 2
    assert store.claim_job() is None
    assert record_failure(store, seeded["job_id"], "two")["backoff_seconds"] == 4
    terminal = record_failure(store, seeded["job_id"], "three")
    assert terminal["status"] == "dead_letter"
    assert store.retry_job(seeded["job_id"])["status"] == "queued"
    assert store.retry_job(seeded["job_id"]) is None


def test_drain_wait_is_bounded_and_tracks_claimed_work():
    shutdown._reset_for_tests()


def test_drain_atomically_blocks_claim_registration():
    shutdown._reset_for_tests()
    shutdown.begin_drain()
    called = False

    def claim():
        nonlocal called
        called = True
        return {"job_id": "unexpected"}

    assert shutdown.claim_unless_draining(claim) is None
    assert called is False
    assert shutdown.summary()["running_jobs"] == 0
    shutdown._reset_for_tests()
    shutdown.job_started()
    shutdown.begin_drain()
    started = time.monotonic()
    assert shutdown.wait(0.02) is False
    assert time.monotonic() - started < 0.2
    assert shutdown.summary()["running_jobs"] == 1
    shutdown.job_finished()
    shutdown._reset_for_tests()


def test_retention_preserves_running_job_and_run(tmp_path):
    store = _store(tmp_path)
    seeded = store.enqueue_job({"mock": True}, run_id="active-run")
    store.claim_job()
    with store.engine.begin() as connection:
        connection.execute(insert(runs).values(
            run_id="active-run", created_at="2000-01-01T00:00:00Z",
            completed_at=None, data="{}"))
        connection.execute(update(jobs).where(jobs.c.job_id == seeded["job_id"])
                           .values(created_at="2000-01-01T00:00:00Z"))
    assert purge(store) == {"jobs": 0, "runs": 0}
    assert store.get_job(seeded["job_id"])["status"] == "running"
    with store.engine.connect() as connection:
        assert connection.execute(select(runs.c.run_id)).scalar_one() == "active-run"


def test_snapshot_is_restorable(tmp_path):
    store = _store(tmp_path)
    seeded = store.enqueue_job({"mock": True})
    snapshot = create_snapshot(store, tmp_path / "snapshots")
    with sqlite3.connect(snapshot) as connection:
        row = connection.execute(
            "SELECT job_id, status FROM jobs WHERE job_id = ?", (seeded["job_id"],)
        ).fetchone()
    assert row == (seeded["job_id"], "queued")
