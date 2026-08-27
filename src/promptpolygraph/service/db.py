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
)


class SqlStore:
    """Store protocol + job queue over a SQLAlchemy engine."""

    def __init__(self, url: str):
        self.url = url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, future=True, connect_args=connect_args)
        if url.startswith("sqlite"):
            with self.engine.begin() as c:
                c.execute(text("PRAGMA journal_mode=WAL"))
        _meta.create_all(self.engine)

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
                    priority: int = 0) -> dict[str, str]:
        job_id = new_id()
        run_id = run_id or new_id()
        with self.engine.begin() as c:
            c.execute(jobs.insert(), {
                "job_id": job_id, "run_id": run_id, "status": "queued",
                "priority": priority, "attempts": 0,
                "config": json.dumps(config, default=str), "progress": None,
                "error": None, "created_at": now_iso(),
                "started_at": None, "finished_at": None,
            })
        return {"job_id": job_id, "run_id": run_id}

    def claim_job(self) -> Optional[dict[str, Any]]:
        """Atomically claim the highest-priority queued job; None if none."""
        with self.engine.begin() as c:
            if self.is_postgres:
                row = c.execute(text(
                    "SELECT job_id FROM jobs WHERE status='queued' "
                    "ORDER BY priority DESC, created_at ASC LIMIT 1 "
                    "FOR UPDATE SKIP LOCKED"
                )).first()
            else:
                row = c.execute(
                    select(jobs.c.job_id).where(jobs.c.status == "queued")
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

    return SqlStore(url or get_settings().database_url)
