"""Dependency-free Prometheus exposition for the service's persisted state."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from .db import jobs, responses, scores

if TYPE_CHECKING:
    from .db import SqlStore

_store: SqlStore | None = None


def configure(store: SqlStore) -> None:
    global _store
    _store = store


def _stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def render() -> str:
    """Render current process/store observations in Prometheus text format."""
    current = _store
    samples = {status: 0 for status in ("queued", "running", "done", "failed", "dead_letter")}
    duration_sum = 0.0
    duration_count = 0
    judge_count = 0
    cost = 0.0
    if current is not None:
        with current.engine.connect() as connection:
            for status, count in connection.execute(
                    select(jobs.c.status, func.count()).group_by(jobs.c.status)).all():
                samples[str(status)] = int(count)
            for started, finished in connection.execute(
                    select(jobs.c.started_at, jobs.c.finished_at).where(
                        jobs.c.started_at.is_not(None), jobs.c.finished_at.is_not(None))).all():
                left, right = _stamp(started), _stamp(finished)
                if left is not None and right is not None:
                    duration_sum += max(0.0, (right - left).total_seconds())
                    duration_count += 1
            judge_count = int(connection.execute(select(func.count()).select_from(scores)).scalar_one())
            for payload in connection.execute(select(responses.c.data)).scalars():
                try:
                    value = json.loads(payload).get("cost_usd")
                    if value is not None:
                        cost += float(value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
    total = sum(samples.values())
    failed = samples.get("failed", 0) + samples.get("dead_letter", 0)
    lines = [
        "# HELP promptpolygraph_queue_depth Jobs waiting to be claimed.",
        "# TYPE promptpolygraph_queue_depth gauge",
        f'promptpolygraph_queue_depth {samples.get("queued", 0)}',
        "# HELP promptpolygraph_runs_total Persisted jobs by status.",
        "# TYPE promptpolygraph_runs_total gauge",
    ]
    lines.extend(f'promptpolygraph_runs_total{{status="{status}"}} {count}'
                 for status, count in sorted(samples.items()))
    lines += [
        "# HELP promptpolygraph_judgements_total Persisted judge scores.",
        "# TYPE promptpolygraph_judgements_total gauge",
        f"promptpolygraph_judgements_total {judge_count}",
        "# HELP promptpolygraph_job_duration_seconds Job execution duration.",
        "# TYPE promptpolygraph_job_duration_seconds summary",
        f"promptpolygraph_job_duration_seconds_sum {duration_sum:.9g}",
        f"promptpolygraph_job_duration_seconds_count {duration_count}",
        "# HELP promptpolygraph_errors_total Failed jobs.",
        "# TYPE promptpolygraph_errors_total gauge",
        f"promptpolygraph_errors_total {failed}",
        "# HELP promptpolygraph_error_ratio Failed jobs divided by all jobs.",
        "# TYPE promptpolygraph_error_ratio gauge",
        f"promptpolygraph_error_ratio {(failed / total) if total else 0:.9g}",
        "# HELP promptpolygraph_cost_usd_total Persisted response cost in USD.",
        "# TYPE promptpolygraph_cost_usd_total gauge",
        f"promptpolygraph_cost_usd_total {cost:.9g}",
    ]
    return "\n".join(lines) + "\n"
