"""Runner — the in-process async engine + durable store.

`Runner` fans cases out through an adapter under a concurrency cap with
per-case timeout, retry, optional rate limiting, and resume. `SQLiteStore`
persists runs/cases/responses/scores and a response cache so re-runs and
re-analysis never re-query the target. Both `Store` (the interface) and
`SQLiteStore` (the v1 backend) live here; a Postgres backend can implement
the same `Store` protocol for v1.1 without touching the engine.
"""

from __future__ import annotations

from .runner import Runner, run_corpus
from .store import SQLiteStore, Store

__all__ = ["Runner", "run_corpus", "SQLiteStore", "Store"]
