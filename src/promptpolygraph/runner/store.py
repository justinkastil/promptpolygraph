"""Durable store + response cache.

`Store` is the interface every backend implements. `SQLiteStore` is the v1
local backend (a single file, no server). Methods are synchronous (sqlite3 is
fast for local single-process use); the async runner wraps writes in
`asyncio.to_thread` so the event loop never blocks on disk.

Tables: runs, cases, responses, scores, cache. The cache is keyed by a stable
hash of (adapter signature + prompt) so an identical query is never re-sent.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from ..models import Case, Response, RunMeta, Score

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT, completed_at TEXT,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cases (
    run_id TEXT, case_id TEXT, category TEXT,
    data TEXT NOT NULL,
    PRIMARY KEY (run_id, case_id)
);
CREATE TABLE IF NOT EXISTS responses (
    run_id TEXT, case_id TEXT,
    data TEXT NOT NULL,
    PRIMARY KEY (run_id, case_id)
);
CREATE TABLE IF NOT EXISTS scores (
    run_id TEXT, case_id TEXT,
    data TEXT NOT NULL,
    PRIMARY KEY (run_id, case_id)
);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
"""


class Store(Protocol):
    def save_run(self, meta: RunMeta) -> None: ...
    def get_run(self, run_id: str) -> Optional[RunMeta]: ...
    def list_runs(self) -> list[RunMeta]: ...
    def save_cases(self, run_id: str, cases: Iterable[Case]) -> None: ...
    def get_cases(self, run_id: str) -> list[Case]: ...
    def save_response(self, run_id: str, resp: Response) -> None: ...
    def get_responses(self, run_id: str) -> list[Response]: ...
    def save_score(self, run_id: str, score: Score) -> None: ...
    def get_scores(self, run_id: str) -> list[Score]: ...
    def cache_get(self, key: str) -> Optional[Response]: ...
    def cache_put(self, key: str, resp: Response) -> None: ...
    def close(self) -> None: ...


class SQLiteStore:
    def __init__(self, path: str | Path = "polygraph.sqlite"):
        self.path = str(path)
        Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn = conn
        return conn

    # ─── runs ─────────────────────────────────────────────────────────────
    def save_run(self, meta: RunMeta) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO runs (run_id, created_at, completed_at, data) "
                "VALUES (?, ?, ?, ?)",
                (meta.run_id, meta.created_at, meta.completed_at, meta.model_dump_json()),
            )

    def get_run(self, run_id: str) -> Optional[RunMeta]:
        row = self._conn().execute(
            "SELECT data FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return self._load_run(row[0]) if row else None

    def list_runs(self) -> list[RunMeta]:
        rows = self._conn().execute(
            "SELECT data FROM runs ORDER BY created_at DESC"
        ).fetchall()
        return [self._load_run(r[0]) for r in rows]

    @staticmethod
    def _load_run(blob: str) -> RunMeta:
        """Deserialize a run record, migrating an older schema forward on read."""
        from ..migrations import migrate_run_dict

        return RunMeta.model_validate(migrate_run_dict(json.loads(blob)))

    # ─── cases ────────────────────────────────────────────────────────────
    def save_cases(self, run_id: str, cases: Iterable[Case]) -> None:
        with self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO cases (run_id, case_id, category, data) "
                "VALUES (?, ?, ?, ?)",
                [(run_id, ca.id, ca.category, ca.model_dump_json()) for ca in cases],
            )

    def get_cases(self, run_id: str) -> list[Case]:
        rows = self._conn().execute(
            "SELECT data FROM cases WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [Case.model_validate_json(r[0]) for r in rows]

    # ─── responses ──────────────────────────────────────────────────────────
    def save_response(self, run_id: str, resp: Response) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO responses (run_id, case_id, data) VALUES (?, ?, ?)",
                (run_id, resp.case_id, resp.model_dump_json()),
            )

    def get_responses(self, run_id: str) -> list[Response]:
        rows = self._conn().execute(
            "SELECT data FROM responses WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [Response.model_validate_json(r[0]) for r in rows]

    # ─── scores ───────────────────────────────────────────────────────────
    def save_score(self, run_id: str, score: Score) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO scores (run_id, case_id, data) VALUES (?, ?, ?)",
                (run_id, score.case_id, score.model_dump_json()),
            )

    def get_scores(self, run_id: str) -> list[Score]:
        rows = self._conn().execute(
            "SELECT data FROM scores WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [Score.model_validate_json(r[0]) for r in rows]

    # ─── cache ────────────────────────────────────────────────────────────
    def cache_get(self, key: str) -> Optional[Response]:
        row = self._conn().execute(
            "SELECT data FROM cache WHERE key = ?", (key,)
        ).fetchone()
        return Response.model_validate_json(row[0]) if row else None

    def cache_put(self, key: str, resp: Response) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO cache (key, data) VALUES (?, ?)",
                (key, resp.model_dump_json()),
            )

    def export_jsonl(self, run_id: str, path: str | Path) -> None:
        """Dump every case + response + score as one JSON object per line."""
        cases = {c.id: c for c in self.get_cases(run_id)}
        responses = {r.case_id: r for r in self.get_responses(run_id)}
        scores = {s.case_id: s for s in self.get_scores(run_id)}
        with open(Path(path).expanduser(), "w", encoding="utf-8") as fh:
            for cid, case in cases.items():
                row = {
                    "case": case.model_dump(),
                    "response": responses[cid].model_dump() if cid in responses else None,
                    "score": scores[cid].model_dump() if cid in scores else None,
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def cache_key(adapter_name: str, adapter_sig: dict[str, Any] | None, prompt: str) -> str:
    """Stable key for the response cache."""
    payload = json.dumps(
        {"adapter": adapter_name, "sig": adapter_sig or {}, "prompt": prompt},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
