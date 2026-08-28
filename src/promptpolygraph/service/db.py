"""SQLAlchemy-backed store + durable job queue.

`SqlStore` implements the same `Store` protocol the engine expects (so the
runner/analyzer/etc. are unchanged), over any SQLAlchemy URL — `sqlite:///…`
for local/dev, `postgresql+psycopg://…` for production. It adds a `jobs` table
and a claim protocol so multiple worker containers can pull work safely
(`FOR UPDATE SKIP LOCKED` on Postgres; an immediate transaction on SQLite).

JSON payloads are stored as text via pydantic's `model_dump_json`, which keeps
the schema portable across both backends.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    func,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine

from ..models import Case, Response, RunMeta, Score, new_id, now_iso

_meta = MetaData()

runs = Table(
    "runs", _meta,
    Column("run_id", String(64), primary_key=True),
    Column("created_at", String(40)),
    Column("completed_at", String(40)),
    Column("data", Text, nullable=False),
)
cases = Table(
    "cases", _meta,
    Column("run_id", String(64), index=True),
    Column("case_id", String(64)),
    Column("category", String(80)),
    Column("data", Text, nullable=False),
)
responses = Table(
    "responses", _meta,
    Column("run_id", String(64), index=True),
    Column("case_id", String(64)),
    Column("data", Text, nullable=False),
)
scores = Table(
    "scores", _meta,
    Column("run_id", String(64), index=True),
    Column("case_id", String(64)),
    Column("data", Text, nullable=False),
)
cache = Table(
    "cache", _meta,
    Column("key", String(80), primary_key=True),
    Column("data", Text, nullable=False),
)
jobs = Table(
    "jobs", _meta,
    Column("job_id", String(64), primary_key=True),
    Column("run_id", String(64), index=True),
    Column("status", String(16), index=True),  # queued|running|done|failed|canceled
    Column("priority", Integer, default=0),
    Column("attempts", Integer, default=0),
    Column("config", Text, nullable=False),
    Column("progress", Text),
    Column("error", Text),
    Column("created_at", String(40)),
    Column("started_at", String(40)),
    Column("finished_at", String(40)),
    Column("next_retry_at", String(40), index=True),
    Column("backoff_seconds", Integer),
    Column("workspace_id", String(64), index=True),
)

quota_locks = Table(
    "quota_locks", _meta,
    Column("workspace_id", String(64), primary_key=True),
)


def engine_kwargs(settings: Any, url: str) -> dict[str, Any]:
    """Build engine options without passing pool-only settings to SQLite."""
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_recycle": settings.db_pool_recycle,
        "pool_pre_ping": True,
        "connect_args": {
            "connect_timeout": settings.db_connect_timeout,
            "options": f"-c statement_timeout={settings.db_statement_timeout}",
        },
    }


class SqlStore:
    """Store protocol + job queue over a SQLAlchemy engine."""

    def __init__(self, url: str, settings: Any | None = None):
        self.url = url
        if settings is None:
            from .settings import get_settings
            settings = get_settings()
        self.settings = settings
        self.engine: Engine = create_engine(url, future=True, **engine_kwargs(settings, url))
        if url.startswith("sqlite"):
            with self.engine.begin() as c:
                c.execute(text("PRAGMA journal_mode=WAL"))
        _meta.create_all(self.engine)
        self._ensure_job_columns()

    def _ensure_job_columns(self) -> None:
        """Upgrade legacy databases with the additive retry columns."""
        names = {column["name"] for column in inspect(self.engine).get_columns("jobs")}
        with self.engine.begin() as connection:
            if "next_retry_at" not in names:
                connection.execute(text("ALTER TABLE jobs ADD COLUMN next_retry_at VARCHAR(40)"))
            if "backoff_seconds" not in names:
                connection.execute(text("ALTER TABLE jobs ADD COLUMN backoff_seconds INTEGER"))
            if "workspace_id" not in names:
                connection.execute(text("ALTER TABLE jobs ADD COLUMN workspace_id VARCHAR(64)"))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_jobs_next_retry_at ON jobs (next_retry_at)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_jobs_workspace_id ON jobs (workspace_id)"
            ))

    @property
    def is_postgres(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    # ─── runs ─────────────────────────────────────────────────────────────
    def save_run(self, meta: RunMeta) -> None:
        self._upsert(
            runs, "run_id", meta.run_id,
            {"run_id": meta.run_id, "created_at": meta.created_at,
             "completed_at": meta.completed_at, "data": meta.model_dump_json()},
        )

    def get_run(self, run_id: str) -> Optional[RunMeta]:
        with self.engine.connect() as c:
            row = c.execute(select(runs.c.data).where(runs.c.run_id == run_id)).first()
        return RunMeta.model_validate_json(row[0]) if row else None

    def list_runs(self, limit: int = 100) -> list[RunMeta]:
        with self.engine.connect() as c:
            rows = c.execute(
                select(runs.c.data).order_by(runs.c.created_at.desc()).limit(limit)
            ).all()
        return [RunMeta.model_validate_json(r[0]) for r in rows]

    # ─── cases / responses / scores ─────────────────────────────────────────
    def save_cases(self, run_id: str, items: Iterable[Case]) -> None:
        with self.engine.begin() as c:
            c.execute(cases.delete().where(cases.c.run_id == run_id))
            payload = [
                {"run_id": run_id, "case_id": ca.id, "category": ca.category,
                 "data": ca.model_dump_json()} for ca in items
            ]
            if payload:
                c.execute(cases.insert(), payload)

    def get_cases(self, run_id: str) -> list[Case]:
        with self.engine.connect() as c:
            rows = c.execute(select(cases.c.data).where(cases.c.run_id == run_id)).all()
        return [Case.model_validate_json(r[0]) for r in rows]

    def save_response(self, run_id: str, resp: Response) -> None:
        self._upsert_pair(responses, run_id, resp.case_id, resp.model_dump_json())

    def get_responses(self, run_id: str) -> list[Response]:
        with self.engine.connect() as c:
            rows = c.execute(select(responses.c.data).where(responses.c.run_id == run_id)).all()
        return [Response.model_validate_json(r[0]) for r in rows]

    def save_score(self, run_id: str, score: Score) -> None:
        self._upsert_pair(scores, run_id, score.case_id, score.model_dump_json())

    def get_scores(self, run_id: str) -> list[Score]:
        with self.engine.connect() as c:
            rows = c.execute(select(scores.c.data).where(scores.c.run_id == run_id)).all()
        return [Score.model_validate_json(r[0]) for r in rows]

    # ─── cache ────────────────────────────────────────────────────────────
    def cache_get(self, key: str) -> Optional[Response]:
        with self.engine.connect() as c:
            row = c.execute(select(cache.c.data).where(cache.c.key == key)).first()
        return Response.model_validate_json(row[0]) if row else None

    def cache_put(self, key: str, resp: Response) -> None:
        self._upsert(cache, "key", key, {"key": key, "data": resp.model_dump_json()})

    def export_jsonl(self, run_id: str, path: str | Path) -> None:
        cmap = {c.id: c for c in self.get_cases(run_id)}
        rmap = {r.case_id: r for r in self.get_responses(run_id)}
        smap = {s.case_id: s for s in self.get_scores(run_id)}
        with open(Path(path).expanduser(), "w", encoding="utf-8") as fh:
            for cid, case in cmap.items():
                fh.write(json.dumps({
                    "case": case.model_dump(),
                    "response": rmap[cid].model_dump() if cid in rmap else None,
                    "score": smap[cid].model_dump() if cid in smap else None,
                }, ensure_ascii=False, default=str) + "\n")

    def close(self) -> None:
        self.engine.dispose()

    # ─── job queue ──────────────────────────────────────────────────────────
    def enqueue_job(self, config: dict[str, Any], *, run_id: str | None = None,
                    priority: int = 0, workspace_id: str | None = None) -> dict[str, str]:
        job_id = new_id()
        run_id = run_id or new_id()
        with self.engine.begin() as c:
            c.execute(jobs.insert(), {
                "job_id": job_id, "run_id": run_id, "status": "queued",
                "priority": priority, "attempts": 0,
                "config": json.dumps(config, default=str), "progress": None,
                "error": None, "created_at": now_iso(),
                "started_at": None, "finished_at": None,
                "next_retry_at": None, "backoff_seconds": None,
                "workspace_id": workspace_id,
            })
        return {"job_id": job_id, "run_id": run_id}

    def quota_usage(self, workspace_id: str) -> dict[str, float | int]:
        """Return persisted usage for one workspace in current UTC windows."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self.engine.connect() as c:
            return self._quota_usage(c, workspace_id, day_start, month_start)

    def _quota_usage(self, connection, workspace_id: str, day_start: str,
                     month_start: str) -> dict[str, float | int]:
        owned = jobs.c.workspace_id == workspace_id
        concurrent = connection.execute(select(func.count()).select_from(jobs).where(
            owned, jobs.c.status.in_(("queued", "running")))).scalar_one()
        daily = connection.execute(select(func.count()).select_from(jobs).where(
            owned, jobs.c.created_at >= day_start)).scalar_one()
        run_ids = connection.execute(select(jobs.c.run_id).where(
            owned, jobs.c.created_at >= month_start)).scalars().all()
        monthly_cost = 0.0
        if run_ids:
            payloads = connection.execute(select(responses.c.data).where(
                responses.c.run_id.in_(run_ids))).scalars().all()
            for payload in payloads:
                try:
                    value = json.loads(payload).get("cost_usd")
                    if value is not None:
                        monthly_cost += float(value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
        return {"concurrent_runs": int(concurrent), "jobs_today": int(daily),
                "monthly_cost": monthly_cost}

    def enqueue_with_quota(self, config: dict[str, Any], workspace_id: str, *,
                           max_concurrent_runs: int, jobs_per_day: int,
                           monthly_cost_budget: float, priority: int = 0) -> tuple[dict[str, str] | None, dict[str, float | int], str | None]:
        """Atomically check one workspace's ceilings and enqueue if admitted."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        connection = self.engine.connect()
        try:
            if self.is_postgres:
                transaction = connection.begin()
                connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:workspace))"),
                                   {"workspace": workspace_id})
            else:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                transaction = None
                if not connection.execute(select(quota_locks.c.workspace_id).where(
                        quota_locks.c.workspace_id == workspace_id)).first():
                    connection.execute(quota_locks.insert(), {"workspace_id": workspace_id})
            usage = self._quota_usage(connection, workspace_id, day_start, month_start)
            exceeded = None
            if usage["concurrent_runs"] >= max_concurrent_runs:
                exceeded = "max_concurrent_runs"
            elif usage["jobs_today"] >= jobs_per_day:
                exceeded = "jobs_per_day"
            elif usage["monthly_cost"] >= monthly_cost_budget:
                exceeded = "monthly_cost_budget"
            if exceeded:
                if transaction is not None:
                    transaction.commit()
                else:
                    connection.commit()
                return None, usage, exceeded
            ids = {"job_id": new_id(), "run_id": new_id()}
            connection.execute(jobs.insert(), {
                **ids, "status": "queued", "priority": priority, "attempts": 0,
                "config": json.dumps(config, default=str), "progress": None,
                "error": None, "created_at": created_at, "started_at": None,
                "finished_at": None, "next_retry_at": None, "backoff_seconds": None,
                "workspace_id": workspace_id,
            })
            if transaction is not None:
                transaction.commit()
            else:
                connection.commit()
            return ids, usage, None
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def claim_job(self) -> Optional[dict[str, Any]]:
        """Atomically claim the highest-priority queued job; None if none."""
        with self.engine.begin() as c:
            if self.is_postgres:
                row = c.execute(text(
                    "SELECT job_id FROM jobs WHERE status='queued' "
                    "AND (next_retry_at IS NULL OR next_retry_at <= :now) "
                    "ORDER BY priority DESC, created_at ASC LIMIT 1 "
                    "FOR UPDATE SKIP LOCKED"
                ), {"now": now_iso()}).first()
            else:
                row = c.execute(
                    select(jobs.c.job_id).where(
                        jobs.c.status == "queued",
                        (jobs.c.next_retry_at.is_(None)) | (jobs.c.next_retry_at <= now_iso()),
                    )
                    .order_by(jobs.c.priority.desc(), jobs.c.created_at.asc()).limit(1)
                ).first()
            if not row:
                return None
            job_id = row[0]
            c.execute(
                update(jobs).where(jobs.c.job_id == job_id).values(
                    status="running", started_at=now_iso(),
                    attempts=jobs.c.attempts + 1,
                )
            )
            j = c.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().first()
        return dict(j) if j else None

    def update_job_progress(self, job_id: str, progress: dict[str, Any]) -> None:
        with self.engine.begin() as c:
            c.execute(update(jobs).where(jobs.c.job_id == job_id).values(
                progress=json.dumps(progress, default=str)))

    def finish_job(self, job_id: str, *, status: str, error: str | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(update(jobs).where(jobs.c.job_id == job_id).values(
                status=status, error=error, finished_at=now_iso()))

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        with self.engine.connect() as c:
            j = c.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().first()
        return dict(j) if j else None

    def get_job_for_run(self, run_id: str) -> Optional[dict[str, Any]]:
        with self.engine.connect() as c:
            j = c.execute(
                select(jobs).where(jobs.c.run_id == run_id)
                .order_by(jobs.c.created_at.desc()).limit(1)
            ).mappings().first()
        return dict(j) if j else None

    def list_jobs(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        stmt = select(jobs).order_by(jobs.c.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(jobs.c.status == status)
        with self.engine.connect() as c:
            return [dict(m) for m in c.execute(stmt).mappings().all()]

    def cancel_job(self, job_id: str) -> bool:
        with self.engine.begin() as c:
            res = c.execute(update(jobs).where(
                jobs.c.job_id == job_id, jobs.c.status == "queued"
            ).values(status="canceled", finished_at=now_iso()))
        return res.rowcount > 0

    def retry_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Requeue a terminal job exactly once; active jobs are rejected."""
        with self.engine.begin() as c:
            result = c.execute(update(jobs).where(
                jobs.c.job_id == job_id,
                jobs.c.status.in_(("failed", "dead_letter")),
            ).values(
                status="queued", attempts=0, error=None, finished_at=None,
                started_at=None, next_retry_at=None, backoff_seconds=None,
            ))
            if not result.rowcount:
                return None
            row = c.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().first()
        return dict(row) if row else None

    # ─── helpers ──────────────────────────────────────────────────────────
    def _upsert(self, table: Table, key_col: str, key_val: str, values: dict) -> None:
        with self.engine.begin() as c:
            exists = c.execute(
                select(table.c[key_col]).where(table.c[key_col] == key_val)
            ).first()
            if exists:
                c.execute(update(table).where(table.c[key_col] == key_val).values(**values))
            else:
                c.execute(table.insert(), values)

    def _upsert_pair(self, table: Table, run_id: str, case_id: str, data: str) -> None:
        with self.engine.begin() as c:
            exists = c.execute(
                select(table.c.case_id).where(
                    table.c.run_id == run_id, table.c.case_id == case_id)
            ).first()
            if exists:
                c.execute(update(table).where(
                    table.c.run_id == run_id, table.c.case_id == case_id
                ).values(data=data))
            else:
                c.execute(table.insert(), {"run_id": run_id, "case_id": case_id, "data": data})


def make_store(url: str | None = None) -> SqlStore:
    from .settings import get_settings

    settings = get_settings()
    return SqlStore(url or settings.database_url, settings=settings)
