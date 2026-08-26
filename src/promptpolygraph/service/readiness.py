"""Readiness checks kept separate from process liveness."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select, text

from .db import SqlStore, jobs
from .settings import Settings

Probe = Callable[[], Any]


def check(
    store: SqlStore,
    settings: Settings,
    llm_probe: Probe | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    report: list[dict[str, Any]] = []
    try:
        with store.engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
        report.append({"check": "store", "status": "pass"})
    except Exception as exc:
        report.append({"check": "store", "status": "fail", "detail": str(exc)})

    try:
        with store.engine.connect() as connection:
            depth = int(connection.execute(
                select(func.count()).select_from(jobs).where(jobs.c.status == "queued")
            ).scalar_one())
        status = "pass" if depth <= settings.queue_max_depth else "fail"
        report.append({"check": "queue", "status": status, "depth": depth,
                       "maximum": settings.queue_max_depth})
    except Exception as exc:
        report.append({"check": "queue", "status": "fail", "detail": str(exc)})

    if not settings.readiness_llm_check:
        report.append({"check": "llm", "status": "pass", "detail": "disabled"})
    elif llm_probe is None:
        report.append({"check": "llm", "status": "fail", "detail": "probe not supplied"})
    else:
        try:
            if llm_probe() is False:
                raise RuntimeError("probe returned false")
            report.append({"check": "llm", "status": "pass"})
        except Exception as exc:
            report.append({"check": "llm", "status": "fail", "detail": str(exc)})

    return not any(item["status"] == "fail" for item in report), report
