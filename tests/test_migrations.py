"""Versioned run-record schema + forward migration on read."""

from __future__ import annotations

from promptpolygraph import migrations
from promptpolygraph.models import RunMeta
from promptpolygraph.runner.store import SQLiteStore


def test_current_schema_constant():
    assert migrations.CURRENT_RUN_SCHEMA >= 1


def test_migrate_legacy_record_stamps_version():
    legacy = {"run_id": "abc", "name": "old", "adapter": "demo"}  # no schema_version
    assert migrations.needs_migration(legacy)
    out = migrations.migrate_run_dict(legacy)
    assert out["schema_version"] == migrations.CURRENT_RUN_SCHEMA
    assert out["run_id"] == "abc"  # data preserved
    assert RunMeta.model_validate(out).schema_version == migrations.CURRENT_RUN_SCHEMA


def test_migrate_is_idempotent():
    cur = {"run_id": "x", "schema_version": migrations.CURRENT_RUN_SCHEMA}
    assert not migrations.needs_migration(cur)
    assert migrations.migrate_run_dict(cur) == cur


def test_unknown_future_version_is_not_downgraded():
    future = {"run_id": "x", "schema_version": 999}
    out = migrations.migrate_run_dict(future)
    assert out["schema_version"] == 999  # never downgrade


def test_store_migrates_legacy_run_on_read(tmp_path):
    store = SQLiteStore(tmp_path / "s.sqlite")
    # write a legacy record directly (no schema_version), bypassing the model
    import json
    with store._conn() as c:
        c.execute("INSERT OR REPLACE INTO runs (run_id, created_at, completed_at, data) VALUES (?,?,?,?)",
                  ("legacy1", "2026-01-01", None,
                   json.dumps({"run_id": "legacy1", "name": "old"})))
    meta = store.get_run("legacy1")
    assert meta is not None
    assert meta.schema_version == migrations.CURRENT_RUN_SCHEMA
    assert meta.name == "old"
    # list_runs migrates too
    assert any(m.run_id == "legacy1" for m in store.list_runs())
