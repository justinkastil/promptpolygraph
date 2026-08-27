#!/usr/bin/env python3
"""Founder acceptance for GitHub issues #54, #55, #56, and #57.

User-flow only. Does not prescribe internals beyond the public HTTP
surface and the callables the issues require. Do not weaken this file.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _prepare_env() -> str:
    tmp = tempfile.mkdtemp(prefix="polygraph-accept-5457-")
    config_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "examples",
        "support_bot",
    )
    os.environ.update(
        {
            "POLYGRAPH_DATABASE_URL": f"sqlite:///{tmp}/svc.sqlite",
            "POLYGRAPH_OUT_DIR": f"{tmp}/out",
            "POLYGRAPH_CONFIG_DIR": config_dir,
            "POLYGRAPH_API_KEYS": "test-key",
            "POLYGRAPH_DEFAULT_MOCK": "true",
            "POLYGRAPH_INPROCESS_WORKER": "false",
            "POLYGRAPH_JOB_MAX_ATTEMPTS": "3",
            "POLYGRAPH_JOB_RETENTION_DAYS": "30",
            "POLYGRAPH_RUN_RETENTION_DAYS": "30",
        }
    )
    return tmp


def main() -> int:
    tmp = _prepare_env()
    from promptpolygraph.service.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    from fastapi.testclient import TestClient
    from promptpolygraph.service.app import app, store

    headers = {"X-API-Key": "test-key"}

    with TestClient(app) as client:
        live = client.get("/healthz")
        if live.status_code != 200:
            raise SystemExit(f"FAIL /healthz {live.status_code} {live.text}")

        # ── #54: retry / dead-letter / manual retry ────────────────────────
        try:
            from promptpolygraph.service.retry import record_failure
        except Exception as exc:
            raise SystemExit(
                f"FAIL #54 promptpolygraph.service.retry.record_failure missing: {exc}"
            ) from exc

        seeded = store.enqueue_job({"mock": True})
        claimed = store.claim_job()
        if not claimed or claimed["job_id"] != seeded["job_id"]:
            raise SystemExit("FAIL #54 could not claim seeded job")
        after = record_failure(store, seeded["job_id"], error="transient blip")
        if after.get("status") not in {"queued", "retry_wait", "retrying"}:
            raise SystemExit(
                f"FAIL #54 transient failure should requeue under cap=3, got {after}"
            )
        if not (after.get("backoff_seconds") or after.get("next_retry_at")):
            raise SystemExit(f"FAIL #54 retry recorded no backoff: {after}")

        # Exhaust remaining attempts so the job is dead-lettered.
        for _ in range(10):
            job = store.get_job(seeded["job_id"])
            if not job:
                break
            if job.get("status") in {"failed", "dead_letter", "dead-letter"}:
                break
            if job.get("status") == "queued":
                store.claim_job()
            after = record_failure(store, seeded["job_id"], error="transient blip")
        job = store.get_job(seeded["job_id"])
        if not job or job.get("status") not in {"failed", "dead_letter", "dead-letter"}:
            raise SystemExit(f"FAIL #54 exhausted job not dead-lettered: {job}")

        dlq = client.get("/api/jobs/dead-letter", headers=headers)
        if dlq.status_code != 200:
            raise SystemExit(
                f"FAIL #54 GET /api/jobs/dead-letter {dlq.status_code} {dlq.text}"
            )
        items = dlq.json()
        if not isinstance(items, list):
            raise SystemExit(f"FAIL #54 dead-letter is not a list: {items!r}")
        ids = {item.get("job_id") for item in items}
        if seeded["job_id"] not in ids:
            raise SystemExit("FAIL #54 exhausted job not in dead-letter list")

        retry = client.post(f"/api/jobs/{seeded['job_id']}/retry", headers=headers)
        if retry.status_code != 200:
            raise SystemExit(
                f"FAIL #54 POST /api/jobs/{{id}}/retry {retry.status_code} {retry.text}"
            )
        again = store.get_job(seeded["job_id"])
        if not again or again.get("status") not in {"queued", "running", "retry_wait"}:
            raise SystemExit(f"FAIL #54 manual retry did not requeue: {again}")

        # ── #56: pool + statement timeout settings applied ─────────────────
        try:
            from promptpolygraph.service.db import engine_kwargs
        except Exception as exc:
            raise SystemExit(
                f"FAIL #56 promptpolygraph.service.db.engine_kwargs missing: {exc}"
            ) from exc
        for name in (
            "db_pool_size",
            "db_max_overflow",
            "db_pool_recycle",
            "db_connect_timeout",
            "db_statement_timeout",
        ):
            if not hasattr(settings, name):
                raise SystemExit(f"FAIL #56 missing Settings.{name}")
        pg = engine_kwargs(settings, "postgresql+psycopg://u:p@localhost/db")
        for key in ("pool_size", "max_overflow", "pool_recycle"):
            if key not in pg:
                raise SystemExit(f"FAIL #56 engine_kwargs missing {key}: {pg}")
        if "connect_args" not in pg and "connect_timeout" not in str(pg):
            raise SystemExit(f"FAIL #56 engine_kwargs missing connect timeout: {pg}")
        timeout_blob = str(pg).lower()
        if "statement_timeout" not in timeout_blob and "options" not in timeout_blob:
            raise SystemExit(f"FAIL #56 engine_kwargs missing statement_timeout: {pg}")

        # ── #57: retention GC + restorable backup + SERVICE.md ─────────────
        try:
            from promptpolygraph.service import retention
        except Exception as exc:
            raise SystemExit(f"FAIL #57 promptpolygraph.service.retention missing: {exc}") from exc
        try:
            from promptpolygraph.service import backup
        except Exception as exc:
            raise SystemExit(f"FAIL #57 promptpolygraph.service.backup missing: {exc}") from exc
        for name in ("job_retention_days", "run_retention_days"):
            if not hasattr(settings, name):
                raise SystemExit(f"FAIL #57 missing Settings.{name}")

        aged = store.enqueue_job({"mock": True})
        from sqlalchemy import update
        from promptpolygraph.service.db import jobs

        with store.engine.begin() as connection:
            connection.execute(
                update(jobs)
                .where(jobs.c.job_id == aged["job_id"])
                .values(created_at="2000-01-01T00:00:00Z")
            )
        purged = retention.purge(store)
        leftover = store.get_job(aged["job_id"])
        gone = leftover is None
        archived = bool(leftover) and leftover.get("status") in {
            "purged", "archived", "deleted",
        }
        if not (gone or archived):
            raise SystemExit(
                f"FAIL #57 aged job survived purge: {leftover} (purge={purged})"
            )

        snap = backup.create_snapshot(store, dest=os.path.join(tmp, "backup"))
        snap_path = Path(str(snap))
        if not snap_path.exists() or snap_path.stat().st_size <= 0:
            raise SystemExit(f"FAIL #57 backup helper produced no snapshot: {snap}")

        service_md = Path(__file__).resolve().parents[1] / "docs" / "SERVICE.md"
        text = service_md.read_text(encoding="utf-8").lower()
        if "rds" not in text:
            raise SystemExit("FAIL #57 docs/SERVICE.md missing RDS backup guidance")
        if not any(word in text for word in ("snapshot", "wal", "retention", "backup")):
            raise SystemExit("FAIL #57 docs/SERVICE.md missing backup/WAL/retention")

        # ── #55: drain flips readiness false and logs a summary ────────────
        ready = client.get("/healthz/ready")
        if ready.status_code != 200:
            raise SystemExit(
                f"FAIL #55 /healthz/ready not 200 before drain: {ready.status_code} {ready.text}"
            )
        try:
            from promptpolygraph.service import shutdown as sd
        except Exception as exc:
            raise SystemExit(
                f"FAIL #55 promptpolygraph.service.shutdown missing: {exc}"
            ) from exc
        sd.begin_drain()
        draining = client.get("/healthz/ready")
        if draining.status_code != 503:
            raise SystemExit(
                f"FAIL #55 readiness not 503 after drain start: "
                f"{draining.status_code} {draining.text}"
            )
        still_live = client.get("/healthz")
        if still_live.status_code != 200:
            raise SystemExit(
                f"FAIL #55 liveness changed during drain: {still_live.status_code}"
            )
        summary = sd.summary()
        if not isinstance(summary, dict) or not summary:
            raise SystemExit(f"FAIL #55 no shutdown summary: {summary!r}")

    print("accept: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
