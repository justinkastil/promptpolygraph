"""Worker: claim queued jobs and execute the pipeline.

Run as many worker processes/containers as you want; each safely claims a
distinct job (`FOR UPDATE SKIP LOCKED` on Postgres). The same code also powers
the optional in-process worker the API can run for single-container / local use.

    polygraph-worker            # serve loop
    python -m promptpolygraph.service.worker
"""

from __future__ import annotations

import asyncio
import logging
import signal
import threading
import time
import traceback
from typing import Any

from ..pipeline import run_pipeline
from .db import SqlStore, make_store
from .jobspec import config_from_payload
from .settings import Settings, get_settings
from .webhooks import notify
from . import shutdown
from .retry import record_failure
from .logging import configure as configure_logging

log = logging.getLogger("promptpolygraph.service.worker")


def execute_job(store: SqlStore, job: dict[str, Any], settings: Settings) -> dict | None:
    """Run one claimed job to completion. Returns the pipeline result or None."""
    import json

    job_id = job["job_id"]
    run_id = job["run_id"]
    payload = json.loads(job["config"]) if isinstance(job["config"], str) else job["config"]
    cfg = config_from_payload(payload)

    def progress(stage: str, info: dict) -> None:
        store.update_job_progress(job_id, {"stage": stage, **info})

    try:
        result = asyncio.run(
            run_pipeline(
                cfg, store, run_id=run_id, out_dir=payload.get("out_dir"),
                progress=progress, formats=payload.get("formats"),
            )
        )
        store.finish_job(job_id, status="done")
        notify(payload.get("webhook_url"), {
            "run_id": run_id, "job_id": job_id, "status": "done",
            "overall_pass": result.get("overall_pass"),
            "summary": result.get("summary"),
        })
        log.info("job %s done (run %s)", job_id, run_id)
        return result
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        failed = record_failure(store, job_id, error=err)
        notify(payload.get("webhook_url"), {
            "run_id": run_id, "job_id": job_id, "status": failed["status"], "error": str(exc),
        })
        log.exception("job %s failed (run %s)", job_id, run_id)
        return None


def run_one(store: SqlStore, settings: Settings | None = None) -> bool:
    """Claim and execute a single job. Returns True if one ran, False if idle."""
    settings = settings or get_settings()
    job = shutdown.claim_unless_draining(store.claim_job)
    if not job:
        return False
    try:
        execute_job(store, job, settings)
    finally:
        shutdown.job_finished()
    return True


def serve(store: SqlStore | None = None, settings: Settings | None = None,
          stop: threading.Event | None = None) -> None:
    """Poll-and-execute loop. Runs until `stop` is set (or forever)."""
    settings = settings or get_settings()
    store = store or make_store(settings.database_url)
    log.info("worker serving (db=%s, poll=%ss)", settings.database_url, settings.worker_poll_s)
    while not (stop and stop.is_set()):
        try:
            ran = run_one(store, settings)
        except Exception:
            log.exception("worker loop error")
            ran = False
        if not ran:
            time.sleep(settings.worker_poll_s)


class WorkerHandle:
    def __init__(self, stop: threading.Event, thread: threading.Thread):
        self.stop = stop
        self.thread = thread

    def set(self) -> None:
        self.stop.set()

    def join(self, timeout: float | None = None) -> None:
        self.thread.join(timeout)


def start_background_worker(settings: Settings | None = None) -> WorkerHandle:
    """Start a daemon worker thread (used by the API's in-process mode)."""
    settings = settings or get_settings()
    stop = threading.Event()
    store = make_store(settings.database_url)
    t = threading.Thread(target=serve, args=(store, settings, stop), daemon=True, name="pp-worker")
    t.start()
    return WorkerHandle(stop, t)


def main() -> None:
    configure_logging()
    settings = get_settings()
    stop = threading.Event()

    def _request_drain(_signum, _frame) -> None:
        shutdown.begin_drain()
        stop.set()
        log.info("worker drain requested: %s", shutdown.summary())

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _request_drain)
    serve(settings=settings, stop=stop)
    drained = shutdown.wait(settings.shutdown_drain_seconds)
    log.info("worker shutdown summary: %s drained=%s", shutdown.summary(), drained)


if __name__ == "__main__":
    main()
