"""Versioned run-record schema + forward migration.

Run records are persisted as JSON. As the schema evolves, an old record must
still load — so every record carries a ``schema_version`` and is migrated
forward on read. This keeps historical runs comparable and the store readable
across upgrades, which an audit of a long-lived project depends on.

A migration is a pure ``dict -> dict`` step keyed by the version it upgrades
*from*. `migrate_run_dict` applies them in order up to ``CURRENT_RUN_SCHEMA``
and is idempotent, so re-reading an already-current record is a no-op.
"""

from __future__ import annotations

from typing import Any, Callable

CURRENT_RUN_SCHEMA = 1


def _from_0(data: dict[str, Any]) -> dict[str, Any]:
    """Legacy records (written before schema_version existed) -> v1.

    No field changed at v1; we only stamp the version. Future steps that rename
    or move fields go in their own ``_from_N`` and register below.
    """
    data["schema_version"] = 1
    return data


# from-version -> migration step
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    0: _from_0,
}


def migrate_run_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a run record dict to the current schema. Idempotent."""
    if not isinstance(data, dict):
        return data
    data = dict(data)
    version = int(data.get("schema_version", 0) or 0)
    while version < CURRENT_RUN_SCHEMA:
        step = _MIGRATIONS.get(version)
        if step is None:
            # no path defined for this version — stamp current and stop, rather
            # than refuse to load (forward-compatible, lossless).
            data["schema_version"] = CURRENT_RUN_SCHEMA
            break
        data = step(data)
        new_version = int(data.get("schema_version", version + 1))
        version = new_version if new_version > version else version + 1
    return data


def needs_migration(data: dict[str, Any]) -> bool:
    return int((data or {}).get("schema_version", 0) or 0) < CURRENT_RUN_SCHEMA
