from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import update

from promptpolygraph.models import Case, Response, RunMeta
from promptpolygraph.service import metrics
from promptpolygraph.service.db import SqlStore, jobs
from promptpolygraph.service.logging import JsonFormatter, inbound_trace, span_id_var, trace_id_var


def _settings(**overrides):
    values = {
        "db_pool_size": 1, "db_max_overflow": 1, "db_pool_recycle": 30,
        "db_connect_timeout": 2, "db_statement_timeout": 1000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _store(tmp_path) -> SqlStore:
    return SqlStore(f"sqlite:///{tmp_path}/quota.sqlite", _settings())


def test_metrics_render_covers_required_persisted_signals(tmp_path):
    store = _store(tmp_path)
    seeded = store.enqueue_job({}, workspace_id="tenant-a")
    claimed = store.claim_job()
    assert claimed is not None
    store.save_run(RunMeta(run_id=seeded["run_id"]))
    case = Case(prompt="hello", category="basic")
    store.save_cases(seeded["run_id"], [case])
    store.save_response(seeded["run_id"], Response(
        case_id=case.id, text="hi", latency_ms=12, cost_usd=1.25))
    store.finish_job(seeded["job_id"], status="failed", error="offline failure")
    metrics.configure(store)

    body = metrics.render()
    assert "promptpolygraph_queue_depth" in body
    assert 'promptpolygraph_runs_total{status="failed"} 1' in body
    assert "promptpolygraph_judgements_total" in body
    assert "promptpolygraph_job_duration_seconds_count 1" in body
    assert "promptpolygraph_errors_total 1" in body
    assert "promptpolygraph_cost_usd_total 1.25" in body


def test_json_formatter_adds_trace_context_and_not_headers():
    trace_reset = trace_id_var.set("a" * 32)
    span_reset = span_id_var.set("b" * 16)
    try:
        record = logging.LogRecord("promptpolygraph.service", logging.INFO, __file__, 1,
                                   "request accepted", (), None)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        span_id_var.reset(span_reset)
        trace_id_var.reset(trace_reset)
    assert payload["trace_id"] == "a" * 32
    assert payload["span_id"] == "b" * 16
    assert "api_key" not in payload
    assert inbound_trace(f"00-{'c' * 32}-{'d' * 16}-01") == ("c" * 32, "d" * 16)
    assert inbound_trace("malformed") == (None, None)


def test_quota_enqueue_is_atomic_and_tenant_isolated(tmp_path):
    store = _store(tmp_path)

    def submit(workspace: str):
        return store.enqueue_with_quota(
            {}, workspace, max_concurrent_runs=1, jobs_per_day=10,
            monthly_cost_budget=10.0,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: submit("tenant-a"), range(2)))
    assert sum(ids is not None for ids, _usage, _reason in results) == 1
    assert sum(reason == "max_concurrent_runs" for _ids, _usage, reason in results) == 1
    assert submit("tenant-b")[0] is not None


def test_daily_window_and_real_monthly_cost(tmp_path):
    store = _store(tmp_path)
    old = store.enqueue_job({}, workspace_id="tenant-a")
    current = store.enqueue_job({}, workspace_id="tenant-a")
    stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with store.engine.begin() as connection:
        connection.execute(update(jobs).where(jobs.c.job_id == old["job_id"])
                           .values(created_at=stale, status="done"))
        connection.execute(update(jobs).where(jobs.c.job_id == current["job_id"])
                           .values(status="done"))
    case = Case(prompt="hello", category="basic")
    store.save_response(current["run_id"], Response(
        case_id=case.id, text="hi", latency_ms=2, cost_usd=2.75))

    usage = store.quota_usage("tenant-a")
    assert usage == {"concurrent_runs": 0, "jobs_today": 1, "monthly_cost": 2.75}
    assert store.quota_usage("tenant-b")["monthly_cost"] == 0.0
    denied, _usage, reason = store.enqueue_with_quota(
        {}, "tenant-a", max_concurrent_runs=5, jobs_per_day=1,
        monthly_cost_budget=100.0,
    )
    assert denied is None
    assert reason == "jobs_per_day"
