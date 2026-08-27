"""Consistent, restorable database snapshots."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .db import SqlStore


def create_snapshot(store: SqlStore, dest: str | Path) -> Path:
    """Create a consistent SQLite backup at *dest* and return its path."""
    if store.engine.dialect.name != "sqlite":
        raise ValueError("application snapshots currently support SQLite; use managed RDS snapshots for Postgres")
    target = Path(dest).expanduser()
    if not target.suffix:
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = target / f"promptpolygraph-{stamp}.sqlite"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    source_path = store.engine.url.database
    if not source_path:
        raise ValueError("SQLite database has no on-disk path")
    with sqlite3.connect(source_path) as source, sqlite3.connect(target) as backup:
        source.backup(backup)
    return target
